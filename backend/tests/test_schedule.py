"""Service scheduling, time zones, DST and countdown calculations (pure, no services)."""

import datetime as dt
from zoneinfo import ZoneInfo

from captions.schedule import (
    PHASE_ENDED,
    PHASE_IDLE,
    PHASE_LIVE,
    PHASE_UPCOMING,
    EventSpec,
    ExceptionSpec,
    RecurringSpec,
    compute_campus_schedule,
    countdown_minutes,
    countdown_parts,
    expand_recurring,
    localize,
    occurrences_between,
)

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


def ny(*args) -> dt.datetime:
    return dt.datetime(*args, tzinfo=NY).astimezone(UTC)


def sunday_9(**kw) -> RecurringSpec:
    return RecurringSpec(id=1, campus_id=1, name="Sunday 9 AM", weekday=6, start_time=dt.time(9), end_time=dt.time(10, 30), **kw)


def test_weekly_expansion_returns_each_sunday():
    occs = expand_recurring(sunday_9(), ny(2026, 10, 1), ny(2026, 10, 31))
    assert [o.local_date for o in occs] == [dt.date(2026, 10, d) for d in (4, 11, 18, 25)]
    assert occs[0].start == ny(2026, 10, 4, 9, 0)
    assert occs[0].end == ny(2026, 10, 4, 10, 30)


def test_wall_clock_time_is_kept_across_fall_back():
    # DST ends Sunday 2026-11-01 at 2:00 AM in New York.
    occs = expand_recurring(sunday_9(), ny(2026, 10, 24), ny(2026, 11, 9))
    before, after = occs[0], occs[1]
    assert before.local_date == dt.date(2026, 10, 25)
    assert after.local_date == dt.date(2026, 11, 1)
    assert before.start.hour == 13  # 9:00 EDT = 13:00 UTC
    assert after.start.hour == 14  # 9:00 EST = 14:00 UTC
    assert after.start.astimezone(NY).hour == 9
    assert after.end - after.start == dt.timedelta(minutes=90)


def test_wall_clock_time_is_kept_across_spring_forward():
    # DST starts Sunday 2027-03-14.
    occs = expand_recurring(sunday_9(), ny(2027, 3, 6), ny(2027, 3, 16))
    assert [o.start.astimezone(NY).hour for o in occs] == [9, 9]
    assert [o.start.hour for o in occs] == [14, 13]


def test_nonexistent_local_time_moves_forward():
    # 2:30 AM does not exist on 2027-03-14; it should be treated as 3:30 AM EDT.
    t = localize(dt.date(2027, 3, 14), dt.time(2, 30), NY)
    assert t.astimezone(NY).replace(tzinfo=None) == dt.datetime(2027, 3, 14, 3, 30)


def test_ambiguous_local_time_uses_first_occurrence():
    t = localize(dt.date(2026, 11, 1), dt.time(1, 30), NY)
    assert t == dt.datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # 1:30 EDT


def test_service_window_over_dst_change_has_real_duration():
    # Midnight-crossing service on the fall-back night lasts one extra real hour.
    spec = RecurringSpec(id=2, campus_id=1, name="Vigil", weekday=5, start_time=dt.time(23), end_time=dt.time(3))
    occ = expand_recurring(spec, ny(2026, 10, 31), ny(2026, 11, 2))[0]
    assert occ.local_date == dt.date(2026, 10, 31)
    assert occ.end - occ.start == dt.timedelta(hours=5)


def test_other_time_zone():
    spec = sunday_9(timezone="America/Los_Angeles")
    occ = expand_recurring(spec, ny(2026, 10, 1), ny(2026, 10, 8))[0]
    assert occ.start.astimezone(ZoneInfo("America/Los_Angeles")).hour == 9
    assert occ.start == ny(2026, 10, 4, 12, 0)


def test_disabled_and_validity_range():
    assert expand_recurring(sunday_9(enabled=False), ny(2026, 10, 1), ny(2026, 10, 31)) == []
    occs = expand_recurring(
        sunday_9(valid_from=dt.date(2026, 10, 10), valid_until=dt.date(2026, 10, 20)), ny(2026, 10, 1), ny(2026, 10, 31)
    )
    assert [o.local_date.day for o in occs] == [11, 18]


def test_cancel_and_modify_exceptions():
    excs = [
        ExceptionSpec(schedule_id=1, occurrence_date=dt.date(2026, 10, 11), kind="cancel"),
        ExceptionSpec(schedule_id=1, occurrence_date=dt.date(2026, 10, 18), kind="modify", end_at=ny(2026, 10, 18, 11, 0)),
    ]
    occs = occurrences_between([sunday_9()], [], excs, ny(2026, 10, 1), ny(2026, 10, 31), include_cancelled=True)
    by_day = {o.local_date.day: o for o in occs}
    assert by_day[11].cancelled
    assert by_day[18].end == ny(2026, 10, 18, 11, 0)
    visible = occurrences_between([sunday_9()], [], excs, ny(2026, 10, 1), ny(2026, 10, 31))
    assert 11 not in {o.local_date.day for o in visible}


def test_one_time_events_merge_and_sort():
    ev = EventSpec(id=7, campus_id=1, name="Christmas Eve", kind="holiday", start_at=ny(2026, 12, 24, 19), end_at=ny(2026, 12, 24, 21))
    occs = occurrences_between([sunday_9()], [ev], [], ny(2026, 12, 20), ny(2026, 12, 28))
    assert [o.key for o in occs] == ["r1-2026-12-20", "e7", "r1-2026-12-27"]
    assert occs[1].kind == "holiday"


def test_phases_before_during_after():
    occs = occurrences_between([sunday_9()], [], [], ny(2026, 10, 3), ny(2026, 10, 12))
    s = compute_campus_schedule(occs, ny(2026, 10, 4, 8, 45))
    assert s.phase == PHASE_UPCOMING and s.next.local_date == dt.date(2026, 10, 4)
    assert s.seconds_until_next == 15 * 60
    assert countdown_minutes(s.seconds_until_next) == 15

    s = compute_campus_schedule(occs, ny(2026, 10, 4, 9, 0))
    assert s.phase == PHASE_LIVE and s.current.key == "r1-2026-10-04"

    s = compute_campus_schedule(occs, ny(2026, 10, 4, 10, 30))
    assert s.phase == PHASE_ENDED and s.next.local_date == dt.date(2026, 10, 11)

    s = compute_campus_schedule(occs, ny(2026, 10, 4, 14, 0))
    assert s.phase == PHASE_UPCOMING


def test_idle_when_nothing_scheduled():
    assert compute_campus_schedule([], ny(2026, 10, 4)).phase == PHASE_IDLE


def test_early_access_opens_window_before_official_start():
    occs = occurrences_between([sunday_9(early_access_minutes=15)], [], [], ny(2026, 10, 3), ny(2026, 10, 5))
    assert compute_campus_schedule(occs, ny(2026, 10, 4, 8, 44)).phase == PHASE_UPCOMING
    live = compute_campus_schedule(occs, ny(2026, 10, 4, 8, 46))
    assert live.phase == PHASE_LIVE
    assert live.current.start == ny(2026, 10, 4, 9, 0)


def test_cancelled_service_is_not_live():
    excs = [ExceptionSpec(schedule_id=1, occurrence_date=dt.date(2026, 10, 4), kind="cancel")]
    occs = occurrences_between([sunday_9()], [], excs, ny(2026, 10, 3), ny(2026, 10, 12), include_cancelled=True)
    s = compute_campus_schedule(occs, ny(2026, 10, 4, 9, 30))
    assert s.phase != PHASE_LIVE
    assert s.next.local_date == dt.date(2026, 10, 11)


def test_manual_start_and_extension_overlap():
    manual = EventSpec(id=3, campus_id=1, name="Live", kind="manual", start_at=ny(2026, 10, 4, 10, 0), end_at=ny(2026, 10, 4, 12, 0))
    occs = occurrences_between([sunday_9()], [manual], [], ny(2026, 10, 3), ny(2026, 10, 5))
    s = compute_campus_schedule(occs, ny(2026, 10, 4, 10, 15))
    assert s.phase == PHASE_LIVE
    assert s.current.key == "e3"  # the one ending later wins


def test_countdown_parts_rounding():
    assert countdown_parts(0) == (0, 0, 0, 0)
    assert countdown_parts(-5) == (0, 0, 0, 0)
    assert countdown_parts(59.2) == (0, 0, 1, 0)
    assert countdown_parts(3 * 86400 + 2 * 3600 + 5 * 60 + 7) == (3, 2, 5, 7)
    assert countdown_minutes(14 * 60 + 1) == 15
    assert countdown_minutes(15 * 60) == 15
    assert countdown_minutes(0.5) == 1
    assert countdown_minutes(0) == 0
