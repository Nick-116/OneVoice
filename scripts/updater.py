#!/usr/bin/env python3
"""OneVoice host updater: pulls new versions from GitHub and redeploys.

Runs on the HOST (systemd on the VPS), never inside a container, because it
needs git and Docker. The admin dashboard cannot run commands; it can only
drop a request file into ./updater/ asking to "check" or "apply". This script
validates the request and only ever fast-forwards to <remote>/<branch> of the
already-configured repository.

    python3 scripts/updater.py check     # fetch and report available updates
    python3 scripts/updater.py apply     # backup, pull, rebuild, restart (with rollback)
    python3 scripts/updater.py watch     # service mode: heartbeat + handle dashboard requests

Environment:
    UPDATER_BRANCH         branch to follow (default: main)
    UPDATER_REMOTE         git remote (default: origin)
    UPDATER_COMPOSE_FILES  colon-separated compose files (default: compose.yml)
    UPDATER_CHECK_HOURS    automatic check interval in watch mode (default: 6)
    UPDATER_HEALTH_TIMEOUT seconds to wait for healthy containers (default: 420)

Stdlib only; works with the system python3 on Ubuntu and macOS.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE_DIR = REPO / "updater"
STATUS = STATE_DIR / "status.json"
REQUEST = STATE_DIR / "request.json"
LOG = STATE_DIR / "update.log"
LOCK = STATE_DIR / ".lock"

BRANCH = os.environ.get("UPDATER_BRANCH", "main")
REMOTE = os.environ.get("UPDATER_REMOTE", "origin")
COMPOSE_FILES = [f for f in os.environ.get("UPDATER_COMPOSE_FILES", "compose.yml").split(":") if f]
CHECK_SECONDS = float(os.environ.get("UPDATER_CHECK_HOURS", "6")) * 3600
HEALTH_TIMEOUT = int(os.environ.get("UPDATER_HEALTH_TIMEOUT", "420"))
CONTAINER_UID = 10001  # the admin container's user; it must be able to write request.json


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(msg: str) -> None:
    line = f"{now()} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")
    # Keep the log small: the dashboard shows the tail.
    lines = LOG.read_text().splitlines()
    if len(lines) > 3000:
        LOG.write_text("\n".join(lines[-2000:]) + "\n")


def run(*args: str, check: bool = True, timeout: int = 1800, capture: bool = True) -> str:
    proc = subprocess.run(args, cwd=REPO, capture_output=capture, text=True, timeout=timeout)
    if capture and proc.stdout.strip():
        for line in proc.stdout.strip().splitlines()[-40:]:
            log("  " + line)
    if proc.returncode != 0:
        if capture and proc.stderr.strip():
            for line in proc.stderr.strip().splitlines()[-40:]:
                log("  ! " + line)
        if check:
            raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args[:4])}")
    return proc.stdout if capture else ""


def git(*args: str, check: bool = True) -> str:
    # safe.directory: the service runs as root while the checkout belongs to the deploy user.
    proc = subprocess.run(["git", "-c", f"safe.directory={REPO}", *args], cwd=REPO, capture_output=True, text=True, timeout=300)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def compose(*args: str) -> list[str]:
    cmd = ["docker", "compose"]
    for f in COMPOSE_FILES:
        cmd += ["-f", f]
    return cmd + list(args)


def read_status() -> dict:
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {}


def write_status(**fields) -> dict:
    status = read_status()
    status.update(fields)
    status["heartbeat"] = now()
    status["branch"] = BRANCH
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=2))
    os.chmod(tmp, 0o644)
    tmp.replace(STATUS)
    return status


def version_info() -> dict:
    version = (REPO / "VERSION").read_text().strip() if (REPO / "VERSION").exists() else "unknown"
    return {"current_commit": git("rev-parse", "HEAD"), "current_version": version}


# ---------------------------------------------------------------- check
def check() -> dict:
    write_status(state="checking", message="Checking GitHub for updates…")
    git("fetch", "--quiet", REMOTE, BRANCH)
    target = f"{REMOTE}/{BRANCH}"
    behind = int(git("rev-list", "--count", f"HEAD..{target}"))
    ahead = int(git("rev-list", "--count", f"{target}..HEAD"))
    dirty = [l for l in git("status", "--porcelain", "--untracked-files=no").splitlines() if l.strip()]
    commits = []
    for line in git("log", "--max-count=50", "--format=%h%x1f%s%x1f%an%x1f%cI", f"HEAD..{target}").splitlines():
        sha, subject, author, date = (line.split("\x1f") + ["", "", "", ""])[:4]
        commits.append({"sha": sha, "subject": subject, "author": author, "date": date})
    blocked = None
    if dirty:
        blocked = "The server copy has local file changes; updates are paused so they are not overwritten."
    elif ahead:
        blocked = "The server copy has commits that are not on GitHub; updates are paused."
    status = write_status(
        state="idle",
        message="Up to date" if behind == 0 else f"{behind} update(s) available",
        checked_at=now(),
        latest_commit=git("rev-parse", target),
        behind=behind,
        commits=commits,
        blocked=blocked,
        **version_info(),
    )
    log(f"check: behind={behind} ahead={ahead} dirty={len(dirty)}")
    return status


# ---------------------------------------------------------------- apply
def wait_healthy() -> None:
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        out = subprocess.run(compose("ps", "--all", "--format", "json"), cwd=REPO, capture_output=True, text=True).stdout
        rows = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            rows.extend(parsed if isinstance(parsed, list) else [parsed])
        pending, failed = [], []
        for c in rows:
            svc, state, health = c.get("Service"), c.get("State"), c.get("Health") or ""
            if svc == "migrate":  # one-shot job: must exit 0
                if state == "exited" and int(c.get("ExitCode") or 0) != 0:
                    failed.append("migrate")
                elif state != "exited":
                    pending.append(svc)
                continue
            if state != "running":
                pending.append(svc)
            elif health and health != "healthy":
                if health == "unhealthy":
                    failed.append(svc)
                pending.append(svc)
        if failed:
            raise RuntimeError(f"unhealthy after update: {', '.join(sorted(set(failed)))}")
        if rows and not pending:
            return
        time.sleep(5)
    raise RuntimeError(f"services not healthy within {HEALTH_TIMEOUT}s")


def deploy(commit: str) -> None:
    env = dict(os.environ, APP_COMMIT=commit, APP_BUILT_AT=now())
    # New versions may need new secret files; the script only creates missing ones.
    if (REPO / "scripts" / "generate-secrets.sh").exists():
        run("bash", "scripts/generate-secrets.sh", check=False)
    for args in (compose("build", "--pull"), compose("up", "-d", "--remove-orphans")):
        log("$ " + " ".join(args))
        proc = subprocess.run(args, cwd=REPO, env=env, capture_output=True, text=True, timeout=3600)
        for line in (proc.stdout + proc.stderr).strip().splitlines()[-30:]:
            log("  " + line)
        if proc.returncode != 0:
            raise RuntimeError(f"{args[2]} failed")
    wait_healthy()


def apply() -> dict:
    status = check()
    if status.get("blocked"):
        return write_status(state="failed", message=status["blocked"], finished_at=now())
    if status.get("behind", 0) == 0:
        return write_status(state="idle", message="Already up to date", finished_at=now())
    previous = git("rev-parse", "HEAD")
    target = status["latest_commit"]
    write_status(state="updating", message="Backing up the database…", started_at=now(), previous_commit=previous)
    log(f"apply: {previous[:8]} -> {target[:8]}")
    try:
        if (REPO / "scripts" / "backup.sh").exists():
            run("bash", "scripts/backup.sh", check=False)
        write_status(message="Downloading the new version…")
        git("merge", "--ff-only", target)
        write_status(message="Building and restarting (this takes a few minutes; the dashboard will reconnect)…")
        deploy(target)
    except Exception as e:
        log(f"update failed: {e}; rolling back to {previous[:8]}")
        write_status(state="rolling_back", message=f"Update failed ({e}); restoring the previous version…")
        try:
            git("reset", "--hard", previous)
            deploy(previous)
            return write_status(state="failed", message=f"Update failed and was rolled back: {e}", finished_at=now(), **version_info())
        except Exception as e2:
            log(f"rollback failed: {e2}")
            return write_status(state="failed", message=f"Update AND rollback failed: {e2}. Check the server.", finished_at=now())
    log("update complete")
    check()
    return write_status(state="idle", message="Update installed", finished_at=now(), last_success=now())


# ---------------------------------------------------------------- watch
def take_request() -> str | None:
    try:
        raw = REQUEST.read_text()
    except FileNotFoundError:
        return None
    REQUEST.unlink(missing_ok=True)
    try:
        req = json.loads(raw)
    except ValueError:
        log("ignored malformed request")
        return None
    action = req.get("action") if isinstance(req, dict) else None
    if action not in ("check", "apply"):
        log(f"ignored request with invalid action {str(action)[:20]!r}")
        return None
    log(f"request: {action} (by {str(req.get('by', '?'))[:64]})")
    return action


def watch() -> None:
    last_check = 0.0
    write_status(state="idle", message="Updater started", **version_info())
    while True:
        try:
            action = take_request()
            if action == "apply":
                apply()
                last_check = time.time()
            elif action == "check" or time.time() - last_check > CHECK_SECONDS:
                check()
                last_check = time.time()
            else:
                write_status()  # heartbeat so the dashboard knows the updater is running
        except Exception as e:
            log(f"error: {e}")
            write_status(state="idle", message=f"Last operation failed: {e}")
        time.sleep(5)


def prepare_dir() -> None:
    STATE_DIR.mkdir(exist_ok=True)
    try:
        if os.geteuid() == 0:
            os.chown(STATE_DIR, CONTAINER_UID, CONTAINER_UID)
        os.chmod(STATE_DIR, 0o775 if os.geteuid() == 0 else 0o777)
    except PermissionError:
        pass


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("check", "apply", "watch"):
        print(__doc__)
        return 2
    prepare_dir()
    with LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another updater is already running", file=sys.stderr)
            return 1
        {"check": check, "apply": apply, "watch": watch}[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
