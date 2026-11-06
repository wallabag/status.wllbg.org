#!/usr/bin/env python3
"""Turn a GitHub issue (opened with the status issue form) and its comments
into a cState incident file in content/issues/.

Reads the event from GITHUB_EVENT_NAME / GITHUB_EVENT_PATH and writes
`changed`, `file`, `commit` and `reply` to GITHUB_OUTPUT.

When MASTODON_TOKEN is set, a new incident is posted on Mastodon and its
resolution is posted as a reply to that first post.
"""
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ISSUES_DIR = Path("content/issues")
SITE_URL = "https://status.wallabag.it"
ALLOWED = {"OWNER", "MEMBER", "COLLABORATOR"}
SEVERITIES = ("down", "disrupted", "notice")
SYSTEMS = (
    "wallabag.it service",
    "wallabag.it payment",
    "wallabag.it invoicing",
    "wallabag.it helpdesk",
)
DATE_FMT = "%Y-%m-%d %H:%M:%S"
MASTODON_URL = os.environ.get("MASTODON_URL") or "https://fosstodon.org"
MASTODON_LIMIT = 500
EMOJI = {"down": "🔴", "disrupted": "🟠", "notice": "🔵"}


class UserError(Exception):
    pass


def utc(value):
    """GitHub ISO timestamp -> cState UTC date string."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).strftime(DATE_FMT)


def parse_form(body):
    fields = {}
    for block in re.split(r"^### ", body or "", flags=re.M)[1:]:
        label, _, value = block.partition("\n")
        value = value.strip()
        fields[label.strip()] = "" if value == "_No response_" else value
    return fields


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-") or "incident"


def find_file(number):
    for path in sorted(ISSUES_DIR.glob("*.md")):
        if re.search(rf"^githubIssue: {number}$", path.read_text(), re.M):
            return path
    return None


def set_field(text, key, value):
    """Set (or add) a front-matter field."""
    head, sep, body = text.partition("\n---\n")
    line = f"{key}: {value}"
    if re.search(rf"^{key}:.*$", head, re.M):
        head = re.sub(rf"^{key}:.*$", line, head, count=1, flags=re.M)
    else:
        head += "\n" + line
    return head + sep + body


def get_field(text, key):
    match = re.search(rf"^{key}: *(.*)$", text.partition("\n---\n")[0], re.M)
    return match.group(1).strip() if match else None


def add_update(text, when, message):
    return text.rstrip("\n") + f'\n\n*Update* {{{{< track "{when}" >}}}} — {message.strip()}\n'


def page_url(path):
    return f"{SITE_URL}/issues/{path.stem}/"


def plain(markdown):
    """Markdown -> text for a Mastodon post."""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", markdown)
    text = re.sub(r"\*\*?|`", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def toot(header, message, url, key, reply_to=None):
    """Post on Mastodon, return the status id (None when not configured)."""
    token = os.environ.get("MASTODON_TOKEN")
    if not token:
        return None
    # Mastodon counts every link as 23 characters
    room = MASTODON_LIMIT - len(header) - 23 - 4
    message = plain(message)
    if len(message) > room:
        message = message[: room - 1].rstrip() + "…"
    data = {"status": f"{header}\n\n{message}\n\n{url}", "visibility": "public", "language": "en"}
    if reply_to:
        data["in_reply_to_id"] = reply_to
    request = urllib.request.Request(
        f"{MASTODON_URL.rstrip('/')}/api/v1/statuses",
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            # a re-run of the same workflow does not post twice
            "Idempotency-Key": f"{os.environ.get('GITHUB_REPOSITORY', 'status')}-{key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return str(json.load(response)["id"])


def create(issue):
    fields = parse_form(issue["body"])
    if "Affected systems" not in fields:
        return None  # not opened with the status form

    severity = fields.get("Severity", "").split(" ")[0]
    if severity not in SEVERITIES:
        raise UserError(f"Unknown severity: `{fields.get('Severity')}`.")
    affected = [s.strip() for s in fields["Affected systems"].split(",") if s.strip()]
    unknown = [s for s in affected if s not in SYSTEMS]
    if not affected or unknown:
        raise UserError(f"Unknown affected systems: `{', '.join(unknown) or 'none'}`.")
    message = fields.get("Message", "")
    if not message:
        raise UserError("The message is empty.")

    now = utc(issue["created_at"])
    start = now
    if fields.get("Start (UTC)"):
        try:
            start = datetime.strptime(fields["Start (UTC)"].strip(), "%Y-%m-%d %H:%M").strftime(DATE_FMT)
        except ValueError:
            raise UserError(f"Invalid start date `{fields['Start (UTC)']}`, expected `YYYY-MM-DD HH:MM` (UTC).")

    maintenance = fields.get("Type") == "Scheduled maintenance"
    no_mastodon = "[x]" in fields.get("Mastodon", "").lower()
    notes = []
    toot_message = message
    if maintenance:
        if start > now and severity != "notice":
            notes.append(f"The maintenance is in the future: severity is `notice` for now, comment `/severity {severity}` when it starts.")
            severity = "notice"
        message = "*Scheduled* — " + message

    title = issue["title"].strip()
    name = f"{start[:10].replace('-', '_')}_{slugify(title)}"
    path = ISSUES_DIR / f"{name}.md"
    if path.exists():
        path = ISSUES_DIR / f"{name}-{issue['number']}.md"

    lines = [
        "---",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"date: {start}",
        "pin: true",
        f"informational: {'true' if maintenance else 'false'}",
        f"severity: {severity}",
        "resolved: false",
        "affected:",
        *[f"  - {s}" for s in affected],
        "section: issue",
        f"githubIssue: {issue['number']}",
        "---",
        "",
        message.strip(),
        "",
    ]

    if not no_mastodon:
        if maintenance:
            header = f"🛠️ Scheduled maintenance: {title}\nStarts {start[:16]} UTC"
        else:
            header = f"{EMOJI[severity]} {title}"
        try:
            status_id = toot(header, toot_message, page_url(path), f"{issue['number']}-open")
            if status_id:
                lines.insert(lines.index("---", 1), f'mastodonId: "{status_id}"')
                notes.append("Posted on Mastodon.")
        except Exception as error:  # the status page must be published anyway
            notes.append(f"Mastodon post failed: {error}")

    path.write_text("\n".join(lines))
    return path, f"Status: add {title} (#{issue['number']})", notes


def toot_resolved(path, old, new, title, number):
    """Reply to the first Mastodon post when an incident gets resolved."""
    status_id = (get_field(old, "mastodonId") or "").strip('"')
    if not status_id or get_field(old, "resolved") == "true" or get_field(new, "resolved") != "true":
        return None
    last = new.rstrip().rsplit("*Update* {{< track", 1)
    message = last[1].split("— ", 1)[1] if len(last) == 2 and "— " in last[1] else "Resolved."
    try:
        toot(f"✅ Resolved: {title}", message, page_url(path), f"{number}-resolved", reply_to=status_id)
        return None
    except Exception as error:
        return f"Mastodon post failed: {error}"


def resolve(text, when, message):
    if get_field(text, "resolved") == "true":
        return text
    text = set_field(text, "resolved", "true")
    text = set_field(text, "resolvedWhen", when)
    text = set_field(text, "pin", "false")
    if not message:
        if get_field(text, "informational") == "true":
            message = "The maintenance is now over and the service is available."
        else:
            message = "This issue is now resolved."
    return add_update(text, when, message)


def comment_command(text, comment):
    body = comment["body"].strip()
    command, _, message = body.partition(" ")
    if "\n" in command:
        command, _, rest = body.partition("\n")
        message = rest
    when = utc(comment["created_at"])

    if command == "/update":
        if not message.strip():
            raise UserError("`/update` needs a message.")
        return add_update(text, when, message), "update", False
    if command == "/severity":
        severity, _, message = message.strip().partition(" ")
        if severity not in SEVERITIES:
            raise UserError(f"Severity must be one of {', '.join(SEVERITIES)}.")
        text = set_field(text, "severity", severity)
        if message.strip():
            text = add_update(text, when, message)
        return text, f"severity {severity}", False
    if command == "/resolved":
        return resolve(text, when, message.strip()), "resolve", True
    return None


def main():
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    issue = event["issue"]
    action = event["action"]
    out = {"changed": "false", "file": "", "commit": "", "reply": "", "close": "false"}

    try:
        if event_name == "issues" and action == "opened":
            if issue["author_association"] not in ALLOWED:
                return out
            result = create(issue)
            if result:
                path, out["commit"], notes = result
                out["file"] = str(path)
                out["reply"] = "\n\n".join([f"Published on {page_url(path)} (live in a minute or two)."] + notes)
        else:
            path = find_file(issue["number"])
            if not path:
                return out
            text = path.read_text()
            title = issue["title"].strip()
            new = text
            if event_name == "issues" and action == "closed":
                new = resolve(text, utc(issue["closed_at"]), "")
                out["commit"] = f"Status: resolve {title} (#{issue['number']})"
            elif event_name == "issues" and action == "reopened":
                new = set_field(text, "resolved", "false")
                new = set_field(new, "pin", "true")
                new = re.sub(r"^resolvedWhen:.*\n", "", new, count=1, flags=re.M)
                new = add_update(new, utc(issue["updated_at"]), "This issue has been reopened.")
                out["commit"] = f"Status: reopen {title} (#{issue['number']})"
            elif event_name == "issue_comment":
                if event["comment"]["author_association"] not in ALLOWED:
                    return out
                result = comment_command(text, event["comment"])
                if not result:
                    return out
                new, verb, close = result
                out["commit"] = f"Status: {verb} {title} (#{issue['number']})"
                out["close"] = "true" if close and issue["state"] == "open" else "false"
            if new != text:
                path.write_text(new)
                out["file"] = str(path)
                replies = []
                if event_name == "issue_comment":
                    replies.append(f"Status page updated: {page_url(path)}")
                mastodon_error = toot_resolved(path, text, new, title, issue["number"])
                if mastodon_error:
                    replies.append(mastodon_error)
                out["reply"] = "\n\n".join(replies)
    except UserError as error:
        out["reply"] = f"Status page not updated: {error}"

    out["changed"] = "true" if out["file"] else "false"
    return out


if __name__ == "__main__":
    result = main()
    with open(os.environ.get("GITHUB_OUTPUT", "/dev/stdout"), "a") as fh:
        for key, value in result.items():
            if "\n" in value:
                fh.write(f"{key}<<EOF_STATUS\n{value}\nEOF_STATUS\n")
            else:
                fh.write(f"{key}={value}\n")
    sys.exit(0)
