# wallabag status page

Source of https://status.wallabag.it (cState + Hugo, deployed by Netlify on every push to `master`).

## Publish an incident or a maintenance (works from the GitHub mobile app)

1. Open a new issue with the **Status page incident / maintenance** template and fill in the form.
   A GitHub Action creates the file in `content/issues/` and pushes it to `master`.
2. Comment on the issue to update the status page:
   - `/update <message>`: add an update
   - `/severity down|disrupted|notice [message]`: change the severity (e.g. when a scheduled maintenance starts)
   - `/resolved [message]`: mark it as resolved and close the issue (closing the issue does the same, reopening it reverts it)

Only the repository owners, members and collaborators can publish. The script is in `.github/scripts/status_issue.py`.

## cState Site v5.6.1b

This is the default cState status page website directory/folder.

* Example site repository link (you are here): https://github.com/cstate/example
* Main cState source code repository: https://github.com/cstate/cstate

## Are you updating? Use these commands

Download your site with all the directories. `git clone --recursive <your repo link goes here>`

Update the cState theme submodule. `git submodule foreach git pull origin master`

In the parent directory, type `hugo serve`. Check to see if everything is working.

Then do `git add -A; git commit -m "Update cState"; git push origin <branch, probably main or master>`. Your status page is now updated and uploaded.


## For maintainers (probably not for you)

Maintainers need to update both cstate/cstate and cstate/example for each new version.

Download this repo with all the directories. `git clone --recursive -b master https://github.com/cstate/example.git`

Add your changes from cstate/cstate's exampleSite folder.

Update the cState theme submodule. `git submodule foreach git pull origin master`

Then push `git add -A; git commit -m "Update cState vX.X.X"; git push origin master`.

## License

MIT © Mantas Vilčinskas
