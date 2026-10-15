"""Software updates (admin only).

The admin container has no Docker or git access by design. It talks to the
host updater (scripts/updater.py) through a shared folder: it writes a small
request file ({"action": "check"|"apply"}) and reads status.json / update.log.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..netutil import client_ip
from .auth import AuthContext, require_admin
from .deps import audit, get_db, get_redis

router = APIRouter(prefix="/api/updates", tags=["updates"])

UPDATER_OFFLINE_AFTER = 30  # seconds without a heartbeat


class ApplyIn(BaseModel):
    model_config = {"extra": "forbid"}
    force: bool = False


def updater_dir() -> Path:
    return Path(os.environ.get("UPDATER_DIR", "/app/updater"))


def _version() -> str:
    for candidate in (Path("/app/VERSION"), Path(__file__).resolve().parents[3] / "VERSION"):
        try:
            return candidate.read_text().strip()
        except OSError:
            continue
    return "dev"


def installed() -> dict:
    return {
        "version": _version(),
        "commit": os.environ.get("APP_COMMIT", "unknown"),
        "built_at": os.environ.get("APP_BUILT_AT") or None,
    }


def _parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_state() -> dict:
    d = updater_dir()
    try:
        status = json.loads((d / "status.json").read_text())
    except (OSError, ValueError):
        status = None
    try:
        log_tail = (d / "update.log").read_text().splitlines()[-80:]
    except OSError:
        log_tail = []
    heartbeat = _parse_time(status.get("heartbeat")) if status else None
    return {
        "installed": installed(),
        "updater_online": heartbeat is not None and time.time() - heartbeat < UPDATER_OFFLINE_AFTER,
        "updater_installed": d.is_dir(),
        "status": status,
        "pending_request": (d / "request.json").exists(),
        "log": log_tail,
    }


def write_request(action: str, username: str) -> str:
    d = updater_dir()
    if not d.is_dir():
        raise HTTPException(503, "The updater is not installed on this server (see docs/UPDATES.md)")
    req_id = uuid.uuid4().hex
    tmp = d / f".request-{req_id}.tmp"
    tmp.write_text(json.dumps({"action": action, "id": req_id, "by": username, "at": time.time()}))
    tmp.replace(d / "request.json")
    return req_id


@router.get("")
async def get_updates(ctx: AuthContext = Depends(require_admin)):
    return read_state()


@router.post("/check")
async def request_check(request: Request, ctx: AuthContext = Depends(require_admin), db=Depends(get_db)):
    req_id = write_request("check", ctx.user.username)
    await audit(db, ctx, "update_check_requested", "updates", ip=client_ip(request))
    return {"ok": True, "id": req_id}


@router.post("/apply")
async def request_apply(body: ApplyIn, request: Request, ctx: AuthContext = Depends(require_admin), db=Depends(get_db),
                        redis=Depends(get_redis)):
    state = read_state()
    if not state["updater_online"]:
        raise HTTPException(503, "The updater is not running on the server")
    st = state["status"] or {}
    if st.get("state") in ("updating", "rolling_back"):
        raise HTTPException(409, "An update is already in progress")
    if not body.force:
        # Restarting containers interrupts captions; don't do it mid-service by accident.
        live = []
        async for key in redis.scan_iter(match="internal:campus:*", count=100):
            raw = await redis.get(key)
            if raw and json.loads(raw).get("phase") == "live":
                live.append(key.rsplit(":", 1)[-1])
        if live:
            raise HTTPException(409, "A service is live right now. Updating restarts the system and interrupts captions; "
                                     "confirm to update anyway.")
    req_id = write_request("apply", ctx.user.username)
    await audit(db, ctx, "update_requested", "updates", ip=client_ip(request), force=body.force,
                to_commit=st.get("latest_commit"))
    return {"ok": True, "id": req_id}

