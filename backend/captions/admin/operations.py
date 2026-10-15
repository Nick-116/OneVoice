"""Monitoring, audio senders, QR codes, languages, providers, settings, users, usage."""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import time
import uuid

import segno
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models as m
from .. import rkeys
from ..config import get_settings
from ..config_store import (
    GENERAL_DEFAULTS,
    STT_PROVIDERS,
    TRANSLATION_PROVIDERS,
    load_general,
    provider_selection,
)
from ..languages import CATALOG_BY_CODE
from ..models import utcnow
from ..netutil import client_ip
from ..providers.translate import TranslationError, build_translation_provider
from ..security import encrypt_secret, hash_password, new_sender_token
from .auth import AuthContext, require_admin, require_user
from .deps import audit, config_changed, get_db, get_redis
from .schemas import (
    GeneralSettingsIn,
    LanguageIn,
    LanguagePatch,
    ProviderIn,
    SenderIn,
    SenderPatch,
    TranslateTestIn,
    UserIn,
    UserPatch,
)
from .services import campus_json, iso

router = APIRouter(prefix="/api", tags=["operations"])


def _num(v, cast=float, default=None):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


async def _audio_status(redis, campus_id: int) -> dict:
    st = await redis.hgetall(rkeys.audio_status(campus_id))
    now = time.time()
    connected = st.get("connected") == "1"
    last_frame = _num(st.get("last_frame_at"))
    return {
        "connected": connected and last_frame is not None and now - last_frame < 5,
        "sender_name": st.get("sender_name"),
        "remote_ip": st.get("remote_ip"),
        "connected_at": _num(st.get("connected_at")),
        "disconnected_at": _num(st.get("disconnected_at")),
        "last_frame_at": last_frame,
        "last_signal_at": _num(st.get("last_signal_at")),
        "level_dbfs": _num(st.get("level_dbfs")),
        "peak_dbfs": _num(st.get("peak_dbfs")),
        "sample_rate": _num(st.get("sample_rate"), int),
        "format": f"{st.get('format', 's16le')} mono" if st else None,
        "forwarding": st.get("live") == "1",
        "bytes": _num(st.get("bytes"), int),
    }


async def _month_cost(db: AsyncSession) -> dict:
    start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = (
        await db.execute(
            select(m.UsageRecord.metric, func.sum(m.UsageRecord.quantity), func.sum(m.UsageRecord.est_cost_usd))
            .where(m.UsageRecord.period_start >= start)
            .group_by(m.UsageRecord.metric)
        )
    ).all()
    out = {"stt_minutes": 0.0, "translation_chars": 0, "est_cost_usd": 0.0}
    for metric, qty, cost in rows:
        if metric == "stt_seconds":
            out["stt_minutes"] = round(float(qty) / 60, 1)
        elif metric == "translation_chars":
            out["translation_chars"] = int(qty)
        out["est_cost_usd"] += float(cost)
    out["est_cost_usd"] = round(out["est_cost_usd"], 2)
    return out


# ---------------------------------------------------------------- overview
@router.get("/overview")
async def overview(ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    campuses = (await db.execute(select(m.Campus).order_by(m.Campus.name))).scalars().all()
    hb = _num(await redis.get(rkeys.WORKER_HEARTBEAT))
    items = []
    for c in campuses:
        raw = await redis.get(rkeys.campus_internal_status(c.id))
        internal = json.loads(raw) if raw else None
        items.append({"campus": campus_json(c), "status": internal, "audio": await _audio_status(redis, c.id)})
    errors = [json.loads(e) for e in await redis.lrange(rkeys.ERRORS_LIST, 0, 9)]
    return {
        "worker": {"alive": hb is not None and time.time() - hb < 10, "heartbeat": hb},
        "campuses": items,
        "recent_errors": errors,
        "usage_month": await _month_cost(db),
        "server_time": time.time(),
    }


@router.get("/errors")
async def recent_errors(limit: int = 100, ctx: AuthContext = Depends(require_user), redis=Depends(get_redis)):
    return [json.loads(e) for e in await redis.lrange(rkeys.ERRORS_LIST, 0, max(0, min(limit, 200) - 1))]


# ---------------------------------------------------------------- audio
@router.get("/audio")
async def audio(ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    campuses = (await db.execute(select(m.Campus).order_by(m.Campus.name))).scalars().all()
    out = []
    for c in campuses:
        history = [json.loads(h) for h in await redis.lrange(rkeys.audio_history(c.id), 0, 49)]
        out.append({"campus": campus_json(c), "audio": await _audio_status(redis, c.id), "history": history})
    return out


# ---------------------------------------------------------------- senders
def _sender_json(s: m.AudioSender) -> dict:
    return {
        "id": str(s.id),
        "campus_id": s.campus_id,
        "name": s.name,
        "allowed_cidrs": s.allowed_cidrs,
        "created_at": iso(s.created_at),
        "revoked_at": iso(s.revoked_at),
    }


@router.get("/senders")
async def list_senders(ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(m.AudioSender).order_by(m.AudioSender.created_at))).scalars().all()
    return [_sender_json(s) for s in rows]


@router.post("/senders", status_code=201)
async def create_sender(body: SenderIn, request: Request, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    campus = await db.get(m.Campus, body.campus_id)
    if not campus:
        raise HTTPException(404, "Campus not found")
    sid = uuid.uuid4()
    token, token_hash = new_sender_token(sid.hex)
    sender = m.AudioSender(id=sid, campus_id=campus.id, name=body.name, token_hash=token_hash, allowed_cidrs=body.allowed_cidrs)
    db.add(sender)
    await db.commit()
    await audit(db, ctx, "sender_created", f"{campus.slug}:{body.name}", ip=client_ip(request))
    # The token is shown exactly once; only its hash is stored.
    return {**_sender_json(sender), "token": token}


@router.patch("/senders/{sender_id}")
async def update_sender(sender_id: uuid.UUID, body: SenderPatch, request: Request, ctx: AuthContext = Depends(require_admin),
                        db: AsyncSession = Depends(get_db)):
    sender = await db.get(m.AudioSender, sender_id)
    if not sender:
        raise HTTPException(404, "Sender not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(sender, k, v)
    await db.commit()
    await audit(db, ctx, "sender_updated", str(sender_id), ip=client_ip(request))
    return _sender_json(sender)


@router.post("/senders/{sender_id}/revoke")
async def revoke_sender(sender_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_admin),
                        db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    sender = await db.get(m.AudioSender, sender_id)
    if not sender:
        raise HTTPException(404, "Sender not found")
    sender.revoked_at = utcnow()
    await db.commit()
    await redis.publish(rkeys.INGEST_REVOKED_CHANNEL, str(sender_id))
    await audit(db, ctx, "sender_revoked", str(sender_id), ip=client_ip(request))
    return _sender_json(sender)


@router.delete("/senders/{sender_id}")
async def delete_sender(sender_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_admin),
                        db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    sender = await db.get(m.AudioSender, sender_id)
    if not sender:
        raise HTTPException(404, "Sender not found")
    await db.delete(sender)
    await db.commit()
    await redis.publish(rkeys.INGEST_REVOKED_CHANNEL, str(sender_id))
    await audit(db, ctx, "sender_deleted", str(sender_id), ip=client_ip(request))
    return {"ok": True}


# ---------------------------------------------------------------- QR codes
async def _public_base(db: AsyncSession) -> str:
    general = await load_general(db)
    return (general.get("public_base_url") or get_settings().public_base_url).rstrip("/")


@router.get("/campuses/{campus_id}/qr")
async def campus_qr(campus_id: int, format: str = "svg", scale: int = 12, ctx: AuthContext = Depends(require_user),
                    db: AsyncSession = Depends(get_db)):
    campus = await db.get(m.Campus, campus_id)
    if not campus:
        raise HTTPException(404, "Campus not found")
    url = f"{await _public_base(db)}/{campus.slug}"
    qr = segno.make(url, error="h")  # high error correction survives printing/scuffs
    scale = max(2, min(scale, 40))
    buf = io.BytesIO()
    filename = f"captions-{campus.slug}"
    if format == "png":
        qr.save(buf, kind="png", scale=scale, border=4)
        media, filename = "image/png", filename + ".png"
    elif format == "svg":
        qr.save(buf, kind="svg", scale=scale, border=4, xmldecl=True)
        media, filename = "image/svg+xml", filename + ".svg"
    else:
        raise HTTPException(422, "format must be svg or png")
    return Response(buf.getvalue(), media_type=media, headers={"Content-Disposition": f'inline; filename="{filename}"',
                                                               "Cache-Control": "no-store"})


@router.get("/qr-links")
async def qr_links(ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    base = await _public_base(db)
    campuses = (await db.execute(select(m.Campus).order_by(m.Campus.name))).scalars().all()
    return [{"campus_id": c.id, "slug": c.slug, "name": c.name, "url": f"{base}/{c.slug}"} for c in campuses]


# ---------------------------------------------------------------- languages
@router.get("/languages")
async def list_languages(ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    rows = (await db.execute(select(m.Language).order_by(m.Language.sort_order, m.Language.code))).scalars().all()
    pc = (await db.execute(select(m.ProviderConfig).where(m.ProviderConfig.kind == "translation"))).scalar_one_or_none()
    translator = build_translation_provider(provider_selection("translation", pc))
    # Current usage: viewers per language across all campuses.
    usage: dict[str, int] = {}
    async for key in redis.scan_iter(match=rkeys.VIEWERS_PATTERN, count=100):
        for field, value in (await redis.hgetall(key)).items():
            lang = field.partition("|")[2]
            usage[lang] = usage.get(lang, 0) + int(value)
    return [
        {
            "code": lang.code,
            "name_en": lang.name_en,
            "native_name": lang.native_name,
            "rtl": lang.rtl,
            "enabled": lang.enabled,
            "sort_order": lang.sort_order,
            "provider_codes": lang.provider_codes,
            "provider_supported": translator.supports(lang.code),
            "builtin": lang.code in CATALOG_BY_CODE,
            "viewers": usage.get(lang.code, 0),
        }
        for lang in rows
    ]


@router.post("/languages", status_code=201)
async def add_language(body: LanguageIn, request: Request, ctx: AuthContext = Depends(require_admin),
                       db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    db.add(m.Language(**body.model_dump()))
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(409, "Language already exists")
    await audit(db, ctx, "language_added", body.code, ip=client_ip(request))
    await config_changed(redis)
    return {"ok": True}


@router.patch("/languages/{code}")
async def update_language(code: str, body: LanguagePatch, request: Request, ctx: AuthContext = Depends(require_admin),
                          db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    lang = await db.get(m.Language, code)
    if not lang:
        raise HTTPException(404, "Language not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            setattr(lang, k, v)
    await db.commit()
    await audit(db, ctx, "language_updated", code, ip=client_ip(request), changes=data)
    await config_changed(redis)
    return {"ok": True}


@router.delete("/languages/{code}")
async def delete_language(code: str, request: Request, ctx: AuthContext = Depends(require_admin),
                          db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    if code in CATALOG_BY_CODE:
        raise HTTPException(400, "Built-in languages can be disabled but not deleted")
    lang = await db.get(m.Language, code)
    if not lang:
        raise HTTPException(404, "Language not found")
    await db.delete(lang)
    await db.commit()
    await audit(db, ctx, "language_deleted", code, ip=client_ip(request))
    await config_changed(redis)
    return {"ok": True}


@router.post("/languages/test")
async def test_translation(body: TranslateTestIn, ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    pc = (await db.execute(select(m.ProviderConfig).where(m.ProviderConfig.kind == "translation"))).scalar_one_or_none()
    sel = provider_selection("translation", pc)
    translator = build_translation_provider(sel)
    lang = await db.get(m.Language, body.target)
    started = time.monotonic()
    try:
        result = await translator.translate([body.text], body.source, body.target, lang.provider_codes if lang else None)
    except TranslationError as e:
        raise HTTPException(502, f"Translation failed: {e}")
    finally:
        await translator.aclose()
    return {"provider": sel.provider, "text": result[0], "latency_ms": round((time.monotonic() - started) * 1000)}


# ---------------------------------------------------------------- providers
@router.get("/providers")
async def get_providers(ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = {p.kind: p for p in (await db.execute(select(m.ProviderConfig))).scalars().all()}
    out = {}
    for kind, options in (("stt", STT_PROVIDERS), ("translation", TRANSLATION_PROVIDERS)):
        sel = provider_selection(kind, rows.get(kind))
        out[kind] = {
            "provider": sel.provider,
            "settings": sel.settings,
            "has_key": sel.has_key,
            "options": {name: defaults for name, defaults in options.items()},
        }
    return out


@router.put("/providers/{kind}")
async def set_provider(kind: str, body: ProviderIn, request: Request, ctx: AuthContext = Depends(require_admin),
                       db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    options = {"stt": STT_PROVIDERS, "translation": TRANSLATION_PROVIDERS}.get(kind)
    if options is None:
        raise HTTPException(404, "Unknown provider kind")
    if body.provider not in options:
        raise HTTPException(422, f"provider must be one of {sorted(options)}")
    allowed_keys = set(options[body.provider])
    unknown = set(body.settings) - allowed_keys
    if unknown:
        raise HTTPException(422, f"unknown settings: {sorted(unknown)}")
    if len(json.dumps(body.settings)) > 8000:
        raise HTTPException(422, "settings too large")
    row = await db.get(m.ProviderConfig, kind)
    if row is None:
        row = m.ProviderConfig(kind=kind, provider=body.provider, settings={})
        db.add(row)
    if row.provider != body.provider:
        row.secret_enc = None  # never reuse one vendor's key for another
    row.provider = body.provider
    row.settings = body.settings
    if body.clear_key:
        row.secret_enc = None
    elif body.api_key:
        row.secret_enc = encrypt_secret(body.api_key)
    await db.commit()
    await audit(db, ctx, "provider_updated", kind, ip=client_ip(request), provider=body.provider,
                key_changed=bool(body.api_key or body.clear_key))
    await config_changed(redis)
    return {"ok": True}


# ---------------------------------------------------------------- general settings
@router.get("/settings")
async def get_general(ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    general = await load_general(db)
    general["effective_public_base_url"] = general["public_base_url"] or get_settings().public_base_url
    return general


@router.put("/settings")
async def put_general(body: GeneralSettingsIn, request: Request, ctx: AuthContext = Depends(require_admin),
                      db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    row = await db.get(m.AppSetting, "general")
    current = dict(row.value) if row else {}
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None and k in GENERAL_DEFAULTS}
    current.update(changes)
    if row is None:
        db.add(m.AppSetting(key="general", value=current))
    else:
        row.value = current
    await db.commit()
    await audit(db, ctx, "settings_updated", "general", ip=client_ip(request), changes=changes)
    await config_changed(redis)
    return await load_general(db)


# ---------------------------------------------------------------- users
def _user_json(u: m.AdminUser) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "mfa_enabled": u.mfa_enabled,
        "disabled": u.disabled,
        "created_at": iso(u.created_at),
        "last_login_at": iso(u.last_login_at),
    }


@router.get("/users")
async def list_users(ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return [_user_json(u) for u in (await db.execute(select(m.AdminUser).order_by(m.AdminUser.username))).scalars().all()]


@router.post("/users", status_code=201)
async def create_user(body: UserIn, request: Request, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = m.AdminUser(username=body.username, display_name=body.display_name, role=body.role,
                       password_hash=hash_password(body.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(409, "Username already exists")
    await audit(db, ctx, "user_created", body.username, ip=client_ip(request), role=body.role)
    return _user_json(user)


@router.patch("/users/{user_id}")
async def update_user(user_id: int, body: UserPatch, request: Request, ctx: AuthContext = Depends(require_admin),
                      db: AsyncSession = Depends(get_db)):
    user = await db.get(m.AdminUser, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == ctx.user.id and (body.disabled or (body.role and body.role != "admin")):
        raise HTTPException(400, "You cannot disable or demote your own account")
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.role is not None:
        user.role = body.role
    if body.disabled is not None:
        user.disabled = body.disabled
    if body.password:
        user.password_hash = hash_password(body.password)
    if body.reset_mfa:
        user.mfa_enabled = False
        user.totp_secret_enc = None
    if body.disabled or body.password or body.reset_mfa:
        await db.execute(m.AdminSession.__table__.delete().where(m.AdminSession.user_id == user.id))
    await db.commit()
    await audit(db, ctx, "user_updated", user.username, ip=client_ip(request),
                changes=[k for k, v in body.model_dump(exclude_unset=True).items() if k != "password" or v])
    return _user_json(user)


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, request: Request, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if user_id == ctx.user.id:
        raise HTTPException(400, "You cannot delete your own account")
    user = await db.get(m.AdminUser, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    await db.delete(user)
    await db.commit()
    await audit(db, ctx, "user_deleted", user.username, ip=client_ip(request))
    return {"ok": True}


# ---------------------------------------------------------------- usage, audit, transcripts
@router.get("/usage")
async def usage(days: int = 30, ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    days = max(1, min(days, 400))
    since = utcnow() - dt.timedelta(days=days)
    day = func.date_trunc("day", m.UsageRecord.period_start)
    rows = (
        await db.execute(
            select(day, m.UsageRecord.campus_id, m.UsageRecord.provider, m.UsageRecord.metric, m.UsageRecord.language,
                   func.sum(m.UsageRecord.quantity), func.sum(m.UsageRecord.est_cost_usd))
            .where(m.UsageRecord.period_start >= since)
            .group_by(day, m.UsageRecord.campus_id, m.UsageRecord.provider, m.UsageRecord.metric, m.UsageRecord.language)
            .order_by(day)
        )
    ).all()
    return {
        "days": days,
        "month": await _month_cost(db),
        "rows": [
            {"day": d.date().isoformat(), "campus_id": c, "provider": p, "metric": metric, "language": lang,
             "quantity": float(q), "est_cost_usd": round(float(cost), 4)}
            for d, c, p, metric, lang, q, cost in rows
        ],
    }


@router.get("/audit")
async def audit_log(limit: int = 200, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(m.AuditLog).order_by(m.AuditLog.at.desc()).limit(max(1, min(limit, 1000))))).scalars().all()
    return [{"at": iso(a.at), "username": a.username, "action": a.action, "target": a.target, "details": a.details, "ip": a.ip}
            for a in rows]


@router.get("/campuses/{campus_id}/transcripts")
async def transcripts(campus_id: int, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(m.Transcript.occurrence_key, m.Transcript.language, func.count(), func.min(m.Transcript.created_at))
            .where(m.Transcript.campus_id == campus_id)
            .group_by(m.Transcript.occurrence_key, m.Transcript.language)
            .order_by(func.min(m.Transcript.created_at).desc())
        )
    ).all()
    return [{"occurrence": o, "language": lang, "segments": n, "started": iso(t)} for o, lang, n, t in rows]


@router.get("/campuses/{campus_id}/transcripts/download")
async def transcript_download(campus_id: int, occurrence: str, language: str, ctx: AuthContext = Depends(require_admin),
                              db: AsyncSession = Depends(get_db)):
    if not re.match(r"^[a-z0-9-]{1,64}$", occurrence) or not re.match(r"^[A-Za-z-]{2,16}$", language):
        raise HTTPException(422, "Invalid occurrence or language")
    rows = (
        await db.execute(
            select(m.Transcript.text)
            .where(m.Transcript.campus_id == campus_id, m.Transcript.occurrence_key == occurrence, m.Transcript.language == language)
            .order_by(m.Transcript.seq)
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(404, "No transcript")
    return PlainTextResponse("\n".join(rows), headers={"Content-Disposition": f'attachment; filename="{occurrence}-{language}.txt"'})
