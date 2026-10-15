"""Admin authentication: password + TOTP MFA, server-side sessions, CSRF.

* Passwords: argon2id.
* Sessions: 256-bit random token in an HttpOnly, Secure, SameSite=Strict
  ``__Host-`` cookie; only its SHA-256 is stored. Idle and absolute expiry.
  The token is rotated after MFA verification (no session fixation).
* MFA: RFC 6238 TOTP. Required for every user unless ADMIN_REQUIRE_MFA=false.
  Codes cannot be replayed within their validity window.
* CSRF: every state-changing request needs ``X-CSRF-Token`` matching the
  session, and a matching ``Origin`` header when the browser sends one.
* Brute force: per-IP and per-username attempt limits in Redis.
"""

from __future__ import annotations

import datetime as dt
import io
import secrets
from dataclasses import dataclass

import pyotp
import segno
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..logging_setup import security_event
from ..models import AdminSession, AdminUser, utcnow
from ..netutil import client_ip
from ..security import (
    DUMMY_PASSWORD_HASH,
    constant_time_equal,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    sha256_hex,
    verify_password,
)
from .deps import audit, get_db, get_redis
from .schemas import CodeIn, LoginIn, PasswordChangeIn

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_WINDOW = 900
MAX_ATTEMPTS_PER_IP = 30
MAX_ATTEMPTS_PER_USER = 8
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def cookie_name() -> str:
    # The __Host- prefix forces Secure, Path=/ and no Domain: cannot be set by subdomains.
    return "__Host-cc_admin" if get_settings().cookie_secure else "cc_admin"


@dataclass
class AuthContext:
    session: AdminSession
    user: AdminUser

    @property
    def mfa_satisfied(self) -> bool:
        if self.session.mfa_verified:
            return True
        return not self.user.mfa_enabled and not get_settings().admin_require_mfa


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        cookie_name(),
        token,
        max_age=s.admin_session_max_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
    )


async def _new_session(db: AsyncSession, user: AdminUser, request: Request, mfa_verified: bool) -> tuple[str, AdminSession]:
    s = get_settings()
    token = secrets.token_urlsafe(32)
    sess = AdminSession(
        token_hash=sha256_hex(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        mfa_verified=mfa_verified,
        expires_at=utcnow() + dt.timedelta(hours=s.admin_session_max_hours),
        last_seen_at=utcnow(),
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:255],
    )
    db.add(sess)
    return token, sess


async def load_auth(request: Request, db: AsyncSession = Depends(get_db)) -> AuthContext:
    token = request.cookies.get(cookie_name())
    if not token or len(token) > 128:
        raise HTTPException(401, "Not authenticated")
    sess = await db.get(AdminSession, sha256_hex(token))
    s = get_settings()
    now = utcnow()
    if sess is None:
        raise HTTPException(401, "Not authenticated")
    idle = now - sess.last_seen_at > dt.timedelta(minutes=s.admin_session_idle_minutes)
    if sess.expires_at <= now or idle or sess.user.disabled:
        await db.delete(sess)
        await db.commit()
        raise HTTPException(401, "Session expired")
    if request.method not in SAFE_METHODS:
        _check_csrf(request, sess)
    if now - sess.last_seen_at > dt.timedelta(seconds=60):
        sess.last_seen_at = now
        await db.commit()
    return AuthContext(sess, sess.user)


def _check_csrf(request: Request, sess: AdminSession) -> None:
    sent = request.headers.get("x-csrf-token", "")
    if not sent or not constant_time_equal(sent, sess.csrf_token):
        security_event("csrf_token_mismatch", ip=client_ip(request), path=request.url.path)
        raise HTTPException(403, "CSRF check failed")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in get_settings().admin_origins:
        security_event("csrf_origin_mismatch", ip=client_ip(request), origin=origin)
        raise HTTPException(403, "CSRF origin check failed")


async def require_user(ctx: AuthContext = Depends(load_auth)) -> AuthContext:
    if not ctx.mfa_satisfied:
        raise HTTPException(403, "Multi-factor authentication required")
    return ctx


async def require_admin(ctx: AuthContext = Depends(require_user)) -> AuthContext:
    if ctx.user.role != "admin":
        raise HTTPException(403, "Administrator role required")
    return ctx


def _user_json(user: AdminUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "mfa_enabled": user.mfa_enabled,
    }


def _mfa_state(ctx: AuthContext) -> str:
    if ctx.mfa_satisfied:
        return "ok"
    return "required" if ctx.user.mfa_enabled else "setup_required"


async def _too_many_attempts(redis, ip: str, username: str) -> bool:
    ip_key, user_key = f"login:ip:{ip}", f"login:user:{username.lower()}"
    ip_n = int(await redis.get(ip_key) or 0)
    user_n = int(await redis.get(user_key) or 0)
    return ip_n >= MAX_ATTEMPTS_PER_IP or user_n >= MAX_ATTEMPTS_PER_USER


async def _record_failure(redis, ip: str, username: str) -> None:
    for key in (f"login:ip:{ip}", f"login:user:{username.lower()}"):
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, LOGIN_WINDOW)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    ip = client_ip(request)
    if await _too_many_attempts(redis, ip, body.username):
        security_event("admin_login_throttled", ip=ip, username=body.username)
        raise HTTPException(429, "Too many login attempts. Try again in 15 minutes.")
    user = (await db.execute(select(AdminUser).where(AdminUser.username == body.username))).scalar_one_or_none()
    ok = verify_password(user.password_hash if user else DUMMY_PASSWORD_HASH, body.password)
    if not user or not ok or user.disabled:
        await _record_failure(redis, ip, body.username)
        security_event("admin_login_failed", ip=ip, username=body.username)
        raise HTTPException(401, "Invalid username or password")
    await redis.delete(f"login:user:{body.username.lower()}")
    token, sess = await _new_session(db, user, request, mfa_verified=False)
    user.last_login_at = utcnow()
    await db.commit()
    _set_cookie(response, token)
    ctx = AuthContext(sess, user)
    await audit(db, ctx, "login", ip=ip)
    return {"user": _user_json(user), "mfa": _mfa_state(ctx), "csrf_token": sess.csrf_token}


@router.post("/logout")
async def logout(response: Response, ctx: AuthContext = Depends(load_auth), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(AdminSession).where(AdminSession.token_hash == ctx.session.token_hash))
    await db.commit()
    response.delete_cookie(cookie_name(), path="/", secure=get_settings().cookie_secure, httponly=True, samesite="strict")
    return {"ok": True}


@router.get("/me")
async def me(ctx: AuthContext = Depends(load_auth)):
    return {"user": _user_json(ctx.user), "mfa": _mfa_state(ctx), "csrf_token": ctx.session.csrf_token}


async def _verify_totp(redis, user: AdminUser, secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    now = dt.datetime.now(dt.timezone.utc)
    for offset in (-1, 0, 1):  # allow 30 s of clock drift either way
        at = now + dt.timedelta(seconds=30 * offset)
        if constant_time_equal(totp.at(at), code):
            counter = int(at.timestamp()) // 30
            # Single use: reject a code that was already accepted.
            if not await redis.set(f"mfa:used:{user.id}:{counter}", "1", nx=True, ex=120):
                return False
            return True
    return False


async def _rotate(db: AsyncSession, ctx: AuthContext, request: Request, response: Response) -> AdminSession:
    await db.delete(ctx.session)
    token, sess = await _new_session(db, ctx.user, request, mfa_verified=True)
    await db.commit()
    _set_cookie(response, token)
    return sess


@router.post("/mfa/verify")
async def mfa_verify(body: CodeIn, request: Request, response: Response, ctx: AuthContext = Depends(load_auth),
                     db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    ip = client_ip(request)
    if not ctx.user.mfa_enabled:
        raise HTTPException(400, "MFA is not enabled for this account")
    if await _too_many_attempts(redis, ip, ctx.user.username):
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    secret = decrypt_secret(ctx.user.totp_secret_enc)
    if not secret or not await _verify_totp(redis, ctx.user, secret, body.code):
        await _record_failure(redis, ip, ctx.user.username)
        security_event("admin_mfa_failed", ip=ip, username=ctx.user.username)
        raise HTTPException(401, "Invalid code")
    sess = await _rotate(db, ctx, request, response)
    await audit(db, AuthContext(sess, ctx.user), "mfa_verified", ip=ip)
    return {"user": _user_json(ctx.user), "mfa": "ok", "csrf_token": sess.csrf_token}


@router.post("/mfa/setup")
async def mfa_setup(ctx: AuthContext = Depends(load_auth), db: AsyncSession = Depends(get_db)):
    """Start (or restart) TOTP enrolment. Only allowed before MFA is enabled."""
    if ctx.user.mfa_enabled:
        raise HTTPException(400, "MFA already enabled; ask an administrator to reset it")
    secret = pyotp.random_base32()
    ctx.user.totp_secret_enc = encrypt_secret(secret)
    await db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=ctx.user.username, issuer_name="OneVoice")
    qr = segno.make(uri, error="m")
    buf = io.BytesIO()
    # Standalone SVG with xmlns: the dashboard shows it as a data: image, which requires the namespace.
    qr.save(buf, kind="svg", scale=5, dark="#111827", xmldecl=False, svgns=True, nl=False)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": buf.getvalue().decode()}


@router.post("/mfa/enable")
async def mfa_enable(body: CodeIn, request: Request, response: Response, ctx: AuthContext = Depends(load_auth),
                     db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    if ctx.user.mfa_enabled:
        raise HTTPException(400, "MFA already enabled")
    secret = decrypt_secret(ctx.user.totp_secret_enc)
    if not secret:
        raise HTTPException(400, "Start MFA setup first")
    if not await _verify_totp(redis, ctx.user, secret, body.code):
        raise HTTPException(401, "Invalid code")
    ctx.user.mfa_enabled = True
    sess = await _rotate(db, ctx, request, response)
    await audit(db, AuthContext(sess, ctx.user), "mfa_enabled", ip=client_ip(request))
    return {"user": _user_json(ctx.user), "mfa": "ok", "csrf_token": sess.csrf_token}


@router.post("/password")
async def change_password(body: PasswordChangeIn, request: Request, ctx: AuthContext = Depends(require_user),
                          db: AsyncSession = Depends(get_db)):
    if not verify_password(ctx.user.password_hash, body.current_password):
        raise HTTPException(400, "Current password is incorrect")
    ctx.user.password_hash = hash_password(body.new_password)
    # Sign out every other session for this user.
    await db.execute(
        delete(AdminSession).where(AdminSession.user_id == ctx.user.id, AdminSession.token_hash != ctx.session.token_hash)
    )
    await db.commit()
    await audit(db, ctx, "password_changed", ip=client_ip(request))
    return {"ok": True}
