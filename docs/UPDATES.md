# Updates from GitHub

The admin dashboard's **Updates** page shows the installed version and any new commits on the GitHub `main` branch. It can install them with one click.

## How it works (and why it's safe)

```
Admin dashboard ──writes──► ./updater/request.json  {"action": "check" | "apply"}
                ◄──reads─── ./updater/status.json, update.log
                                     ▲
                    scripts/updater.py (host service, systemd)
                    git fetch / fast-forward → docker compose build → up -d → health check
```

* **No Docker access in the dashboard.** The admin container can't run commands or reach Docker. All it can do is drop a request file saying "check" or "apply". The updater accepts only those two words.
* **The updater only follows GitHub `main`** of the repository the server was cloned from. It fast-forwards with `--ff-only` and never accepts a version or URL from the dashboard.
* **Before installing**, it backs up the database (`scripts/backup.sh`). After building, it waits for every container to report healthy. If anything fails, it resets to the previous commit and rebuilds that version, so a bad update is **rolled back automatically**.
* **Local changes on the server pause updates.** If the server's checkout has edited files, the page explains this instead of overwriting them.
* **During a live service** the dashboard asks for a second confirmation, because an update restarts the system and interrupts captions for a few minutes.

> **Security note:** anyone who can push to the GitHub `main` branch can, through this updater, change the software running on your server. Protect the GitHub account with 2-factor authentication. Consider enabling branch protection for `main` (Settings → Branches) if other people get write access.

## Install the updater on the VPS

The app should be a `git clone` of your repository, e.g. in `/opt/onevoice`.

```bash
cd /opt/onevoice
sudo cp deploy/updater/onevoice-updater.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now onevoice-updater
sudo systemctl status onevoice-updater     # should say "active (running)"
```

The Updates page should show **Updater: Running on the server** within a few seconds. The updater checks GitHub automatically every 6 hours, and on demand with **Check now**.

If the app lives somewhere other than `/opt/onevoice`, edit `WorkingDirectory` and `ExecStart` in the service file before copying it.

Manual use (same thing the service does):
```bash
sudo python3 scripts/updater.py check
sudo python3 scripts/updater.py apply
```

## Local testing on a Mac

```bash
python3 scripts/updater.py watch
```
Leave it running in a terminal. The dashboard at http://localhost:18081/updates will show it as running.

## Releasing an update

1. Make and test your changes locally (`docker compose -f compose.test.yml run --rm tests`).
2. Bump `VERSION` (e.g. `1.1.0` → `1.2.0`) when the change is meaningful.
3. Commit and push to `main`. GitHub Actions runs the test suite on every push.
4. On the dashboard: **Updates → Check now → Install update**.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Updater: Not installed" | The `./updater` folder doesn't exist yet. Start the service once, or run `sudo python3 scripts/updater.py check`. |
| "Updater: Not running" | `sudo systemctl status onevoice-updater` and `journalctl -u onevoice-updater -n 100` |
| "The server copy has local file changes" | `git status` on the server. Keep settings in `.env`, `secrets/` and the dashboard, never in tracked files. Undo local edits with `git stash` or `git checkout -- <file>`. |
| Update failed and was rolled back | The log on the Updates page shows the failing step. The previous version is running again; fix the problem in GitHub and try again. |
