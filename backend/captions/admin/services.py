"""Campus, schedule and live-service management routes."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models as m
from ..config_store import event_spec, exception_spec, load_general, recurring_spec
from ..netutil import client_ip
from ..schedule import Occurrence, compute_campus_schedule, occurrences_between
from .auth import AuthContext, require_admin, require_user
from .deps import audit, config_changed, get_db, get_redis
from .schemas import (
    CampusIn,
    CampusPatch,
    EventIn,
    EventPatch,
    ExtendIn,
    OccurrenceRef,
    ScheduleIn,
    SchedulePatch,
    StartIn,
)

router = APIRouter(prefix="/api", tags=["services"])
UTC = dt.timezone.utc


def iso(d: dt.datetime | None) -> str | None:
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z") if d else None


def campus_json(c: m.Campus) -> dict:
    return {
        "id": c.id,
        "slug": c.slug,
        "name": c.name,
        "timezone": c.timezone,
        "source_language": c.source_language,
        "default_language": c.default_language,
        "enabled": c.enabled,
        "retain_transcripts": c.retain_transcripts,
        "languages": c.language_codes,
    }


def schedule_json(s: m.ServiceSchedule) -> dict:
    return {
        "id": s.id,
        "campus_id": s.campus_id,
        "name": s.name,
        "weekday": s.weekday,
        "start_time": s.start_time.strftime("%H:%M"),
        "end_time": s.end_time.strftime("%H:%M"),
        "timezone": s.timezone,
        "enabled": s.enabled,
        "early_access_minutes": s.early_access_minutes,
        "languages": s.languages,
        "valid_from": s.valid_from.isoformat() if s.valid_from else None,
        "valid_until": s.valid_until.isoformat() if s.valid_until else None,
    }


def event_json(e: m.ServiceEvent) -> dict:
    return {
        "id": e.id,
        "campus_id": e.campus_id,
        "name": e.name,
        "kind": e.kind,
        "start_at": iso(e.start_at),
        "end_at": iso(e.end_at),
        "early_access_minutes": e.early_access_minutes,
        "cancelled": e.cancelled,
        "languages": e.languages,
    }


def occurrence_json(o: Occurrence) -> dict:
    return {
        "key": o.key,
        "campus_id": o.campus_id,
        "name": o.name,
        "kind": o.kind,
        "start": iso(o.start),
        "end": iso(o.end),
        "window_start": iso(o.window_start),
        "cancelled": o.cancelled,
        "schedule_id": o.schedule_id,
        "event_id": o.event_id,
        "local_date": o.local_date.isoformat() if o.local_date else None,
    }


async def _validate_languages(db: AsyncSession, codes: list[str] | None) -> None:
    if not codes:
        return
    known = set((await db.execute(select(m.Language.code).where(m.Language.code.in_(codes)))).scalars())
    missing = [c for c in codes if c not in known]
    if missing:
        raise HTTPException(422, f"Unknown language(s): {', '.join(missing)}")


async def _campus_or_404(db: AsyncSession, campus_id: int) -> m.Campus:
    c = await db.get(m.Campus, campus_id)
    if not c:
        raise HTTPException(404, "Campus not found")
    return c


async def campus_occurrences(
    db: AsyncSession, campus_id: int, start: dt.datetime, end: dt.datetime, include_cancelled: bool = True
) -> list[Occurrence]:
    scheds = (await db.execute(select(m.ServiceSchedule).where(m.ServiceSchedule.campus_id == campus_id))).scalars().all()
    events = (
        await db.execute(
            select(m.ServiceEvent).where(m.ServiceEvent.campus_id == campus_id, m.ServiceEvent.end_at > start - dt.timedelta(days=1))
        )
    ).scalars().all()
    sched_ids = [s.id for s in scheds]
    excs = []
    if sched_ids:
        excs = (
            await db.execute(select(m.ScheduleException).where(m.ScheduleException.schedule_id.in_(sched_ids)))
        ).scalars().all()
    return occurrences_between(
        [recurring_spec(s) for s in scheds],
        [event_spec(e) for e in events],
        [exception_spec(x) for x in excs],
        start,
        end,
        include_cancelled=include_cancelled,
    )


async def current_occurrence(db: AsyncSession, campus_id: int) -> Occurrence | None:
    now = dt.datetime.now(UTC)
    occs = await campus_occurrences(db, campus_id, now - dt.timedelta(days=1), now + dt.timedelta(days=1), include_cancelled=False)
    sched = compute_campus_schedule(occs, now)
    return sched.current


# ---------------------------------------------------------------- campuses
@router.get("/campuses")
async def list_campuses(ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(m.Campus).order_by(m.Campus.name))).scalars().all()
    return [campus_json(c) for c in rows]


@router.post("/campuses", status_code=201)
async def create_campus(body: CampusIn, request: Request, ctx: AuthContext = Depends(require_admin),
                        db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    await _validate_languages(db, [*body.languages, body.source_language, body.default_language])
    campus = m.Campus(**body.model_dump(exclude={"languages"}))
    langs = list(dict.fromkeys([body.source_language, *body.languages]))
    campus.languages = [m.CampusLanguage(language_code=code) for code in langs]
    db.add(campus)
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(409, "A campus with that slug already exists")
    await db.refresh(campus)
    await audit(db, ctx, "campus_created", campus.slug, ip=client_ip(request))
    await config_changed(redis)
    return campus_json(campus)


@router.patch("/campuses/{campus_id}")
async def update_campus(campus_id: int, body: CampusPatch, request: Request, ctx: AuthContext = Depends(require_admin),
                        db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    campus = await _campus_or_404(db, campus_id)
    data = body.model_dump(exclude_unset=True)
    langs = data.pop("languages", None)
    await _validate_languages(db, [*(langs or []), *[v for k, v in data.items() if k.endswith("_language") and v]])
    for k, v in data.items():
        if v is not None:
            setattr(campus, k, v)
    if langs is not None:
        wanted = set([campus.source_language, *langs])
        # Diff rather than replace, so unchanged rows are not deleted and re-inserted.
        campus.languages = [cl for cl in campus.languages if cl.language_code in wanted]
        have = {cl.language_code for cl in campus.languages}
        campus.languages.extend(m.CampusLanguage(campus_id=campus.id, language_code=c) for c in wanted - have)
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(409, "A campus with that slug already exists")
    await db.refresh(campus)
    await audit(db, ctx, "campus_updated", campus.slug, ip=client_ip(request), changes=list(data) + (["languages"] if langs is not None else []))
    await config_changed(redis)
    return campus_json(campus)


@router.delete("/campuses/{campus_id}")
async def delete_campus(campus_id: int, request: Request, ctx: AuthContext = Depends(require_admin),
                        db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    campus = await _campus_or_404(db, campus_id)
    slug = campus.slug
    await db.delete(campus)
    await db.commit()
    await audit(db, ctx, "campus_deleted", slug, ip=client_ip(request))
    await config_changed(redis)
    return {"ok": True}


# ---------------------------------------------------------------- recurring schedules
@router.get("/schedules")
async def list_schedules(campus_id: int | None = None, ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    q = select(m.ServiceSchedule).order_by(m.ServiceSchedule.campus_id, m.ServiceSchedule.weekday, m.ServiceSchedule.start_time)
    if campus_id is not None:
        q = q.where(m.ServiceSchedule.campus_id == campus_id)
    return [schedule_json(s) for s in (await db.execute(q)).scalars().all()]


@router.post("/schedules", status_code=201)
async def create_schedule(body: ScheduleIn, request: Request, ctx: AuthContext = Depends(require_admin),
                          db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    await _campus_or_404(db, body.campus_id)
    await _validate_languages(db, body.languages)
    sched = m.ServiceSchedule(**body.model_dump())
    db.add(sched)
    await db.commit()
    await audit(db, ctx, "schedule_created", f"{sched.id}:{sched.name}", ip=client_ip(request))
    await config_changed(redis)
    return schedule_json(sched)


@router.patch("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, body: SchedulePatch, request: Request, ctx: AuthContext = Depends(require_admin),
                          db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    sched = await db.get(m.ServiceSchedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Schedule not found")
    data = body.model_dump(exclude_unset=True)
    if "campus_id" in data:
        await _campus_or_404(db, data["campus_id"])
    await _validate_languages(db, data.get("languages"))
    for k, v in data.items():
        setattr(sched, k, v)
    if sched.start_time == sched.end_time:
        raise HTTPException(422, "start and end time must differ")
    await db.commit()
    await audit(db, ctx, "schedule_updated", f"{sched.id}:{sched.name}", ip=client_ip(request), changes=list(data))
    await config_changed(redis)
    return schedule_json(sched)


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, request: Request, ctx: AuthContext = Depends(require_admin),
                          db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    sched = await db.get(m.ServiceSchedule, schedule_id)
    if not sched:
        raise HTTPException(404, "Schedule not found")
    await db.delete(sched)
    await db.commit()
    await audit(db, ctx, "schedule_deleted", f"{schedule_id}:{sched.name}", ip=client_ip(request))
    await config_changed(redis)
    return {"ok": True}


# ---------------------------------------------------------------- one-time events
@router.get("/events")
async def list_events(campus_id: int | None = None, include_past: bool = False, ctx: AuthContext = Depends(require_user),
                      db: AsyncSession = Depends(get_db)):
    q = select(m.ServiceEvent).order_by(m.ServiceEvent.start_at)
    if campus_id is not None:
        q = q.where(m.ServiceEvent.campus_id == campus_id)
    if not include_past:
        q = q.where(m.ServiceEvent.end_at > dt.datetime.now(UTC) - dt.timedelta(days=1))
    return [event_json(e) for e in (await db.execute(q.limit(500))).scalars().all()]


@router.post("/events", status_code=201)
async def create_event(body: EventIn, request: Request, ctx: AuthContext = Depends(require_admin),
                       db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    await _campus_or_404(db, body.campus_id)
    await _validate_languages(db, body.languages)
    ev = m.ServiceEvent(**body.model_dump())
    db.add(ev)
    await db.commit()
    await audit(db, ctx, "event_created", f"{ev.id}:{ev.name}", ip=client_ip(request))
    await config_changed(redis)
    return event_json(ev)


@router.patch("/events/{event_id}")
async def update_event(event_id: int, body: EventPatch, request: Request, ctx: AuthContext = Depends(require_admin),
                       db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    ev = await db.get(m.ServiceEvent, event_id)
    if not ev:
        raise HTTPException(404, "Event not found")
    data = body.model_dump(exclude_unset=True)
    await _validate_languages(db, data.get("languages"))
    for k, v in data.items():
        setattr(ev, k, v)
    if ev.end_at <= ev.start_at:
        raise HTTPException(422, "end_at must be after start_at")
    await db.commit()
    await audit(db, ctx, "event_updated", f"{ev.id}:{ev.name}", ip=client_ip(request), changes=list(data))
    await config_changed(redis)
    return event_json(ev)


@router.delete("/events/{event_id}")
async def delete_event(event_id: int, request: Request, ctx: AuthContext = Depends(require_admin),
                       db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    ev = await db.get(m.ServiceEvent, event_id)
    if not ev:
        raise HTTPException(404, "Event not found")
    await db.delete(ev)
    await db.commit()
    await audit(db, ctx, "event_deleted", f"{event_id}:{ev.name}", ip=client_ip(request))
    await config_changed(redis)
    return {"ok": True}


# ---------------------------------------------------------------- occurrences
@router.get("/campuses/{campus_id}/occurrences")
async def upcoming(campus_id: int, days: int = 14, ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    await _campus_or_404(db, campus_id)
    days = max(1, min(days, 90))
    now = dt.datetime.now(UTC)
    occs = await campus_occurrences(db, campus_id, now - dt.timedelta(hours=6), now + dt.timedelta(days=days))
    return [occurrence_json(o) for o in occs]


def _parse_key(key: str) -> tuple[str, int, dt.date | None]:
    if key.startswith("e"):
        return "e", int(key[1:]), None
    sid, date = key[1:].split("-", 1)
    return "r", int(sid), dt.date.fromisoformat(date)


async def _upsert_exception(db: AsyncSession, schedule_id: int, date: dt.date, **fields) -> m.ScheduleException:
    exc = (
        await db.execute(
            select(m.ScheduleException).where(
                m.ScheduleException.schedule_id == schedule_id, m.ScheduleException.occurrence_date == date
            )
        )
    ).scalar_one_or_none()
    if exc is None:
        exc = m.ScheduleException(schedule_id=schedule_id, occurrence_date=date, **fields)
        db.add(exc)
    else:
        for k, v in fields.items():
            setattr(exc, k, v)
    return exc


@router.post("/occurrences/cancel")
async def cancel_occurrence(body: OccurrenceRef, request: Request, ctx: AuthContext = Depends(require_user),
                            db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    kind, ident, date = _parse_key(body.key)
    if kind == "e":
        ev = await db.get(m.ServiceEvent, ident)
        if not ev:
            raise HTTPException(404, "Event not found")
        ev.cancelled = True
    else:
        if not await db.get(m.ServiceSchedule, ident):
            raise HTTPException(404, "Schedule not found")
        await _upsert_exception(db, ident, date, kind="cancel", start_at=None, end_at=None)
    await db.commit()
    await audit(db, ctx, "occurrence_cancelled", body.key, ip=client_ip(request))
    await config_changed(redis)
    return {"ok": True}


@router.post("/occurrences/restore")
async def restore_occurrence(body: OccurrenceRef, request: Request, ctx: AuthContext = Depends(require_user),
                             db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    kind, ident, date = _parse_key(body.key)
    if kind == "e":
        ev = await db.get(m.ServiceEvent, ident)
        if not ev:
            raise HTTPException(404, "Event not found")
        ev.cancelled = False
    else:
        exc = (
            await db.execute(
                select(m.ScheduleException).where(
                    m.ScheduleException.schedule_id == ident, m.ScheduleException.occurrence_date == date
                )
            )
        ).scalar_one_or_none()
        if exc:
            await db.delete(exc)
    await db.commit()
    await audit(db, ctx, "occurrence_restored", body.key, ip=client_ip(request))
    await config_changed(redis)
    return {"ok": True}


# ---------------------------------------------------------------- live controls (operators allowed)
@router.post("/campuses/{campus_id}/start")
async def start_service(campus_id: int, body: StartIn, request: Request, ctx: AuthContext = Depends(require_user),
                        db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    campus = await _campus_or_404(db, campus_id)
    if not campus.enabled:
        raise HTTPException(409, "Campus is disabled")
    if await current_occurrence(db, campus_id):
        raise HTTPException(409, "A service is already live at this campus")
    general = await load_general(db)
    minutes = body.duration_minutes or int(general["manual_default_minutes"])
    now = dt.datetime.now(UTC)
    ev = m.ServiceEvent(campus_id=campus_id, name=body.name, kind="manual", start_at=now, end_at=now + dt.timedelta(minutes=minutes))
    db.add(ev)
    await db.commit()
    await audit(db, ctx, "service_started", campus.slug, ip=client_ip(request), minutes=minutes)
    await config_changed(redis)
    return event_json(ev)


@router.post("/campuses/{campus_id}/stop")
async def stop_service(campus_id: int, request: Request, ctx: AuthContext = Depends(require_user),
                       db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    campus = await _campus_or_404(db, campus_id)
    occ = await current_occurrence(db, campus_id)
    if not occ:
        raise HTTPException(409, "No service is live at this campus")
    now = dt.datetime.now(UTC)
    if occ.event_id is not None:
        ev = await db.get(m.ServiceEvent, occ.event_id)
        if ev.start_at < now:
            ev.end_at = now
        else:
            ev.cancelled = True  # still in early access: nothing to keep
    else:
        assert occ.schedule_id is not None and occ.local_date is not None
        if occ.start < now:
            await _upsert_exception(db, occ.schedule_id, occ.local_date, kind="modify", start_at=occ.start, end_at=now,
                                    note=f"ended early by {ctx.user.username}")
        else:
            await _upsert_exception(db, occ.schedule_id, occ.local_date, kind="cancel", start_at=None, end_at=None,
                                    note=f"stopped by {ctx.user.username}")
    await db.commit()
    await audit(db, ctx, "service_stopped", campus.slug, ip=client_ip(request), occurrence=occ.key)
    await config_changed(redis)
    return {"ok": True}


@router.post("/campuses/{campus_id}/extend")
async def extend_service(campus_id: int, body: ExtendIn, request: Request, ctx: AuthContext = Depends(require_user),
                         db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    campus = await _campus_or_404(db, campus_id)
    occ = await current_occurrence(db, campus_id)
    if not occ:
        raise HTTPException(409, "No service is live at this campus")
    new_end = occ.end + dt.timedelta(minutes=body.minutes)
    if occ.event_id is not None:
        ev = await db.get(m.ServiceEvent, occ.event_id)
        ev.end_at = new_end
    else:
        assert occ.schedule_id is not None and occ.local_date is not None
        await _upsert_exception(db, occ.schedule_id, occ.local_date, kind="modify", start_at=occ.start, end_at=new_end,
                                note=f"extended by {ctx.user.username}")
    await db.commit()
    await audit(db, ctx, "service_extended", campus.slug, ip=client_ip(request), minutes=body.minutes, occurrence=occ.key)
    await config_changed(redis)
    return {"ok": True, "end": iso(new_end)}
