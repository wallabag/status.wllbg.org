#!/usr/bin/env python3
"""Turn a GitHub issue (opened with the status issue form) and its comments
into a cState incident file in content/issues/.

Reads the event from GITHUB_EVENT_NAME / GITHUB_EVENT_PATH and writes
`changed`, `file`, `commit` and `reply` to GITHUB_OUTPUT.
"""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ISSUES_DIR = Path("content/issues")
SITE_URL = "https://status.wallabag.org"
ALLOWED = {"OWNER", "MEMBER", "COLLABORATOR"}
SEVERITIES = ("down", "disrupted", "notice")
SYSTEMS = ("wallabag.it service", "wallabag.it homepage", "wallabag software homepage")
DATE_FMT = "%Y-%m-%d %H:%M:%S"


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
    notes = []
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
    path.write_text("\n".join(lines))
    return path, f"Status: add {title} (#{issue['number']})", notes


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
                out["reply"] = "\n\n".join([f"Published on {SITE_URL}/issues/{path.stem}/ (live in a minute or two)."] + notes)
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
                if event_name == "issue_comment":
                    out["reply"] = f"Status page updated: {SITE_URL}/issues/{path.stem}/"
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
