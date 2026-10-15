import { describe, expect, it } from 'vitest';
import { isoToZonedLocal, to12h, tzOffsetMinutes, zonedLocalToIso, zonedLocalToUtcMs } from './time';

describe('zonedLocalToIso', () => {
  it('uses daylight offset in summer for New York', () => {
    expect(zonedLocalToIso('2026-07-04T10:30', 'America/New_York')).toBe('2026-07-04T10:30:00-04:00');
  });

  it('uses standard offset in winter for New York', () => {
    expect(zonedLocalToIso('2026-12-24T23:00', 'America/New_York')).toBe('2026-12-24T23:00:00-05:00');
  });

  it('handles zones without DST and half-hour offsets', () => {
    expect(zonedLocalToIso('2026-07-04T09:00', 'America/Phoenix')).toBe('2026-07-04T09:00:00-07:00');
    expect(zonedLocalToIso('2026-01-15T18:45', 'Asia/Kolkata')).toBe('2026-01-15T18:45:00+05:30');
    expect(zonedLocalToIso('2026-03-01T00:00', 'UTC')).toBe('2026-03-01T00:00:00+00:00');
  });

  it('is independent of the browser time zone (produces the correct instant)', () => {
    expect(new Date(zonedLocalToUtcMs('2026-10-18T09:00', 'America/Los_Angeles')).toISOString()).toBe(
      '2026-10-18T16:00:00.000Z',
    );
  });

  it('shifts non-existent spring-forward times forward', () => {
    // 2026-03-08 02:30 does not exist in New York (clocks jump 02:00 → 03:00).
    expect(zonedLocalToIso('2026-03-08T02:30', 'America/New_York')).toBe('2026-03-08T03:30:00-04:00');
  });

  it('resolves ambiguous fall-back times to the first occurrence', () => {
    // 2026-11-01 01:30 happens twice in New York; pick EDT (-04:00).
    expect(zonedLocalToIso('2026-11-01T01:30', 'America/New_York')).toBe('2026-11-01T01:30:00-04:00');
  });

  it('round-trips with isoToZonedLocal', () => {
    for (const tz of ['America/New_York', 'America/Chicago', 'Europe/London', 'Australia/Sydney']) {
      const local = '2026-05-17T08:15';
      expect(isoToZonedLocal(zonedLocalToIso(local, tz), tz)).toBe(local);
    }
    expect(isoToZonedLocal('2026-12-25T05:00:00Z', 'America/New_York')).toBe('2026-12-25T00:00');
  });

  it('rejects malformed input', () => {
    expect(() => zonedLocalToIso('2026-12-25 10:00', 'America/New_York')).toThrow();
  });
});

describe('helpers', () => {
  it('computes offsets', () => {
    expect(tzOffsetMinutes('America/New_York', Date.UTC(2026, 0, 1))).toBe(-300);
    expect(tzOffsetMinutes('America/New_York', Date.UTC(2026, 6, 1))).toBe(-240);
  });

  it('formats 12-hour times', () => {
    expect(to12h('00:05')).toBe('12:05 AM');
    expect(to12h('09:30')).toBe('9:30 AM');
    expect(to12h('12:00')).toBe('12:00 PM');
    expect(to12h('18:45')).toBe('6:45 PM');
  });
});
