"""First-run setup: create the first administrator, then pick providers.

While no administrator exists, the admin service prints a one-time setup code
to its log (``docker compose logs admin``). Creating the first account requires
that code, so nobody else who can reach the dashboard first (for example on
the same network) can claim it. Afterwards the dashboard walks the new admin
through MFA enrolment and provider setup.
"""

from __future__ import annotations

import logging
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models as m
from ..config_store import provider_selection
from ..logging_setup import security_event
from ..models import utcnow
from ..netutil import client_ip
from ..security import constant_time_equal, hash_password, sha256_hex
from .auth import AuthContext, _new_session, _set_cookie, _user_json, require_admin
from .deps import audit, get_db, get_redis

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/setup", tags=["setup"])

SETUP_CODE_KEY = "setup:code"
SETUP_ATTEMPTS_PREFIX = "setup:attempts:"
MAX_ATTEMPTS = 10
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion


class SetupAdminIn(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}
    setup_code: str = Field(min_length=4, max_length=32)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._@-]+$")
    display_name: str = Field(default="", max_length=120)
    password: str = Field(min_length=12, max_length=256)


async def admin_count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(m.AdminUser))).scalar_one())


def _normalize(code: str) -> str:
    return code.upper().replace("-", "").replace(" ", "")


async def ensure_setup_code(redis, db: AsyncSession) -> None:
    """Create and log a setup code if there are no admins and none is pending."""
    if await admin_count(db) > 0 or await redis.exists(SETUP_CODE_KEY):
        return
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    code = f"{raw[:4]}-{raw[4:]}"
    await redis.set(SETUP_CODE_KEY, sha256_hex(_normalize(code)))
    banner = "=" * 64
    log.warning(
        f"\n{banner}\n  OneVoice first-run setup code: {code}\n"
        f"  Open the admin dashboard and enter this code to create the first admin.\n{banner}"
    )


async def setup_complete(db: AsyncSession) -> bool:
    row = await db.get(m.AppSetting, "setup")
    if row and row.value.get("completed"):
        return True
    # Installs created before the wizard existed: configured providers mean setup was done by hand.
    kinds = set((await db.execute(select(m.ProviderConfig.kind))).scalars())
    return {"stt", "translation"} <= kinds


@router.get("/status")
async def status(db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    needs_admin = await admin_count(db) == 0
    if needs_admin:
        await ensure_setup_code(redis, db)
    return {"needs_admin": needs_admin, "setup_complete": (not needs_admin) and await setup_complete(db)}


@router.post("/admin")
async def create_first_admin(body: SetupAdminIn, request: Request, response: Response,
                             db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    ip = client_ip(request)
    attempts_key = SETUP_ATTEMPTS_PREFIX + ip
    if int(await redis.get(attempts_key) or 0) >= MAX_ATTEMPTS:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    # Serialize concurrent attempts so two people cannot both become "first" admin.
    await db.execute(text("SELECT pg_advisory_xact_lock(4242001)"))
    if await admin_count(db) > 0:
        raise HTTPException(409, "Setup has already been completed. Sign in instead.")
    expected = await redis.get(SETUP_CODE_KEY)
    if not expected or not constant_time_equal(expected, sha256_hex(_normalize(body.setup_code))):
        n = await redis.incr(attempts_key)
        if n == 1:
            await redis.expire(attempts_key, 900)
        security_event("setup_code_rejected", ip=ip)
        raise HTTPException(403, "That setup code is not correct. Find it with: docker compose logs admin")
    user = m.AdminUser(username=body.username, display_name=body.display_name, role="admin",
                       password_hash=hash_password(body.password), last_login_at=utcnow())
    db.add(user)
    await db.flush()
    token, sess = await _new_session(db, user, request, mfa_verified=False)
    await db.commit()
    await redis.delete(SETUP_CODE_KEY, attempts_key)
    _set_cookie(response, token)
    log.info("first administrator created", extra={"fields": {"username": user.username, "ip": ip}})
    await audit(db, AuthContext(sess, user), "first_admin_created", user.username, ip=ip)
    return {"user": _user_json(user), "mfa": "setup_required", "csrf_token": sess.csrf_token}


@router.post("/complete")
async def complete(request: Request, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    row = await db.get(m.AppSetting, "setup")
    value = {"completed": True, "completed_at": utcnow().isoformat(), "by": ctx.user.username}
    if row is None:
        db.add(m.AppSetting(key="setup", value=value))
    else:
        row.value = value
    await db.commit()
    await audit(db, ctx, "setup_completed", "setup", ip=client_ip(request))
    return {"ok": True}


# ---------------------------------------------------------------- provider key checks
async def check_stt_credentials(provider: str, api_key: str | None, client: httpx.AsyncClient) -> tuple[bool, str]:
    if provider == "simulated":
        return True, "Simulated speech-to-text needs no key (testing only)."
    if not api_key:
        return False, "No API key saved yet."
    try:
        if provider == "deepgram":
            r = await client.get("https://api.deepgram.com/v1/projects", headers={"Authorization": f"Token {api_key}"})
        elif provider == "assemblyai":
            r = await client.get("https://api.assemblyai.com/v2/transcript", params={"limit": 1},
                                 headers={"Authorization": api_key})
        else:
            return False, f"Unknown provider {provider!r}"
    except httpx.HTTPError as e:
        return False, f"Could not reach {provider}: {e.__class__.__name__}"
    if r.status_code == 200:
        return True, "The key works."
    if r.status_code in (401, 403):
        return False, "The provider rejected this key."
    return False, f"Unexpected response from {provider} (HTTP {r.status_code})."


@router.post("/test-stt")
async def test_stt(ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Verify the saved speech-to-text key without streaming any audio (no cost)."""
    row = await db.get(m.ProviderConfig, "stt")
    sel = provider_selection("stt", row)
    async with httpx.AsyncClient(timeout=10) as client:
        ok, message = await check_stt_credentials(sel.provider, sel.api_key, client)
    return {"provider": sel.provider, "ok": ok, "message": message}
