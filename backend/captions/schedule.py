"""Service scheduling engine.

Pure functions with no I/O so they can be unit tested exhaustively.

Recurring schedules are stored as wall-clock times in an IANA time zone and
expanded per local date, so "Sunday 9:00 AM America/New_York" is always 9:00 AM
local time on both sides of a DST change. Times that do not exist (spring
forward gap) are shifted forward; ambiguous times (fall back) use the first
occurrence (fold=0), matching how people read a clock.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc


@dataclass(frozen=True)
class RecurringSpec:
    id: int
    campus_id: int
    name: str
    weekday: int  # 0 = Monday ... 6 = Sunday
    start_time: dt.time
    end_time: dt.time
    timezone: str = "America/New_York"
    enabled: bool = True
    early_access_minutes: int = 0
    languages: tuple[str, ...] | None = None
    valid_from: dt.date | None = None
    valid_until: dt.date | None = None


@dataclass(frozen=True)
class EventSpec:
    id: int
    campus_id: int
    name: str
    start_at: dt.datetime
    end_at: dt.datetime
    kind: str = "special"
    early_access_minutes: int = 0
    cancelled: bool = False
    languages: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ExceptionSpec:
    schedule_id: int
    occurrence_date: dt.date
    kind: str  # cancel | modify
    start_at: dt.datetime | None = None
    end_at: dt.datetime | None = None


@dataclass(frozen=True)
class Occurrence:
    key: str
    campus_id: int
    name: str
    kind: str  # recurring | special | holiday | manual
    start: dt.datetime  # official start (UTC)
    end: dt.datetime  # UTC
    early_access_minutes: int = 0
    cancelled: bool = False
    languages: tuple[str, ...] | None = None
    schedule_id: int | None = None
    event_id: int | None = None
    local_date: dt.date | None = None

    @property
    def window_start(self) -> dt.datetime:
        """When captions actually open (official start minus early access)."""
        return self.start - dt.timedelta(minutes=self.early_access_minutes)

    def is_active(self, now: dt.datetime) -> bool:
        return not self.cancelled and self.window_start <= now < self.end


def localize(local_date: dt.date, local_time: dt.time, tz: ZoneInfo) -> dt.datetime:
    """Combine a local wall-clock date/time into an aware UTC datetime.

    With fold=0, zoneinfo applies the offset in effect *before* a transition:
    a non-existent 2:30 AM (spring forward) becomes 3:30 AM local, and an
    ambiguous 1:30 AM (fall back) resolves to the first, daylight-time 1:30.
    """
    naive = dt.datetime.combine(local_date, local_time)
    return naive.replace(tzinfo=tz, fold=0).astimezone(UTC)


def expand_recurring(
    spec: RecurringSpec,
    range_start: dt.datetime,
    range_end: dt.datetime,
    exceptions: dict[tuple[int, dt.date], ExceptionSpec] | None = None,
) -> list[Occurrence]:
    """All occurrences of ``spec`` overlapping [range_start, range_end)."""
    if not spec.enabled:
        return []
    tz = ZoneInfo(spec.timezone)
    exceptions = exceptions or {}
    # Pad by one day on each side so services crossing midnight are found.
    first = range_start.astimezone(tz).date() - dt.timedelta(days=1)
    last = range_end.astimezone(tz).date() + dt.timedelta(days=1)
    out: list[Occurrence] = []
    day = first + dt.timedelta(days=(spec.weekday - first.weekday()) % 7)
    while day <= last:
        if (spec.valid_from is None or day >= spec.valid_from) and (
            spec.valid_until is None or day <= spec.valid_until
        ):
            start = localize(day, spec.start_time, tz)
            end_day = day if spec.end_time > spec.start_time else day + dt.timedelta(days=1)
            end = localize(end_day, spec.end_time, tz)
            cancelled = False
            exc = exceptions.get((spec.id, day))
            if exc is not None:
                if exc.kind == "cancel":
                    cancelled = True
                elif exc.kind == "modify":
                    start = exc.start_at or start
                    end = exc.end_at or end
            occ = Occurrence(
                key=f"r{spec.id}-{day.isoformat()}",
                campus_id=spec.campus_id,
                name=spec.name,
                kind="recurring",
                start=start,
                end=end,
                early_access_minutes=spec.early_access_minutes,
                cancelled=cancelled,
                languages=spec.languages,
                schedule_id=spec.id,
                local_date=day,
            )
            if occ.end > range_start and occ.window_start < range_end:
                out.append(occ)
        day += dt.timedelta(days=7)
    return out


def event_occurrence(ev: EventSpec) -> Occurrence:
    return Occurrence(
        key=f"e{ev.id}",
        campus_id=ev.campus_id,
        name=ev.name,
        kind=ev.kind,
        start=ev.start_at.astimezone(UTC),
        end=ev.end_at.astimezone(UTC),
        early_access_minutes=ev.early_access_minutes,
        cancelled=ev.cancelled,
        languages=ev.languages,
        event_id=ev.id,
    )


def occurrences_between(
    recurring: Iterable[RecurringSpec],
    events: Iterable[EventSpec],
    exceptions: Iterable[ExceptionSpec],
    range_start: dt.datetime,
    range_end: dt.datetime,
    include_cancelled: bool = False,
) -> list[Occurrence]:
    exc_map = {(e.schedule_id, e.occurrence_date): e for e in exceptions}
    occs: list[Occurrence] = []
    for spec in recurring:
        occs.extend(expand_recurring(spec, range_start, range_end, exc_map))
    for ev in events:
        occ = event_occurrence(ev)
        if occ.end > range_start and occ.window_start < range_end:
            occs.append(occ)
    if not include_cancelled:
        occs = [o for o in occs if not o.cancelled]
    occs.sort(key=lambda o: (o.window_start, o.key))
    return occs


# Phases published to the public site.
PHASE_LIVE = "live"
PHASE_UPCOMING = "upcoming"
PHASE_ENDED = "ended"
PHASE_IDLE = "idle"


@dataclass
class CampusSchedule:
    phase: str
    current: Occurrence | None = None
    next: Occurrence | None = None
    last_ended: Occurrence | None = None
    seconds_until_next: float | None = None
    upcoming: list[Occurrence] = field(default_factory=list)


def compute_campus_schedule(
    occurrences: Sequence[Occurrence],
    now: dt.datetime,
    ended_grace: dt.timedelta = dt.timedelta(hours=3),
) -> CampusSchedule:
    """Decide what the public site should show for one campus at ``now``.

    * live     - inside an active window (early access counts as live)
    * ended    - a service ended within ``ended_grace`` and none is active
    * upcoming - a future service exists
    * idle     - nothing scheduled in the lookahead range
    """
    active = [o for o in occurrences if not o.cancelled and o.is_active(now)]
    future = [o for o in occurrences if not o.cancelled and o.window_start > now]
    past = [o for o in occurrences if not o.cancelled and o.end <= now]
    nxt = min(future, key=lambda o: o.window_start) if future else None
    last = max(past, key=lambda o: o.end) if past else None

    if active:
        # Overlapping windows: the one ending last wins so an extension is honoured.
        current = max(active, key=lambda o: (o.end, o.key))
        return CampusSchedule(PHASE_LIVE, current=current, next=nxt, last_ended=last, upcoming=future)

    secs = (nxt.start - now).total_seconds() if nxt else None
    if last is not None and now - last.end < ended_grace:
        return CampusSchedule(PHASE_ENDED, next=nxt, last_ended=last, seconds_until_next=secs, upcoming=future)
    if nxt is not None:
        return CampusSchedule(PHASE_UPCOMING, next=nxt, last_ended=last, seconds_until_next=secs, upcoming=future)
    return CampusSchedule(PHASE_IDLE, last_ended=last)


def countdown_parts(seconds: float) -> tuple[int, int, int, int]:
    """Split a countdown into (days, hours, minutes, seconds), never negative.

    Minutes round *up* so "starts in 15 minutes" is shown until it is really 14.
    """
    total = max(0, int(-(-seconds // 1)))  # ceil
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return days, hours, minutes, secs


def countdown_minutes(seconds: float) -> int:
    """Whole minutes for the "Service starts in N minutes" message (ceil)."""
    if seconds <= 0:
        return 0
    return int(-(-seconds // 60))
