// Time-zone helpers built on Intl only (no date library).

const dtfCache = new Map<string, Intl.DateTimeFormat>();

function partsFormatter(tz: string): Intl.DateTimeFormat {
  let f = dtfCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    dtfCache.set(tz, f);
  }
  return f;
}

interface WallParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

function wallParts(tz: string, utcMs: number): WallParts {
  const out: Record<string, number> = {};
  for (const p of partsFormatter(tz).formatToParts(new Date(utcMs))) {
    if (p.type !== 'literal') out[p.type] = Number(p.value);
  }
  return {
    year: out.year ?? 1970,
    month: out.month ?? 1,
    day: out.day ?? 1,
    hour: (out.hour ?? 0) % 24, // some engines render midnight as 24
    minute: out.minute ?? 0,
    second: out.second ?? 0,
  };
}

/** UTC offset of `tz` at instant `utcMs`, in minutes (e.g. -240 for EDT). */
export function tzOffsetMinutes(tz: string, utcMs: number): number {
  const base = Math.floor(utcMs / 1000) * 1000;
  const w = wallParts(tz, base);
  const asUtc = Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, w.second);
  return Math.round((asUtc - base) / 60000);
}

const pad = (n: number, w = 2) => String(Math.abs(n)).padStart(w, '0');

export function formatOffset(minutes: number): string {
  const sign = minutes < 0 ? '-' : '+';
  const a = Math.abs(minutes);
  return `${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

const LOCAL_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

/**
 * Convert a wall-clock time in `tz` (a `<input type="datetime-local">` value, "YYYY-MM-DDTHH:mm")
 * to an instant (epoch ms).
 *
 * * Ambiguous times (DST fall-back hour) resolve to the earlier instant (first occurrence).
 * * Non-existent times (DST spring-forward gap) are shifted forward by the gap length,
 *   e.g. 02:30 on the US spring-forward day becomes 03:30 daylight time.
 */
export function zonedLocalToUtcMs(local: string, tz: string): number {
  const m = LOCAL_RE.exec(local);
  if (!m) throw new Error(`Invalid local date-time: ${local}`);
  const [, y, mo, d, h, mi, s] = m;
  const wall = Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s ?? 0));
  const DAY_HALF = 12 * 3600 * 1000;
  // Offsets either side of any transition near this wall time (transitions are months apart).
  const before = tzOffsetMinutes(tz, wall - DAY_HALF);
  const after = tzOffsetMinutes(tz, wall + DAY_HALF);
  const valid: number[] = [];
  for (const off of before === after ? [before] : [before, after]) {
    const t = wall - off * 60000;
    if (tzOffsetMinutes(tz, t) === off) valid.push(t);
  }
  if (valid.length) return Math.min(...valid);
  // Gap: interpret with the pre-transition offset, which lands after the jump.
  return wall - before * 60000;
}

/** ISO-8601 string with the zone's UTC offset, e.g. "2026-12-24T23:00:00-05:00". */
export function utcMsToZonedIso(utcMs: number, tz: string): string {
  const w = wallParts(tz, utcMs);
  const off = tzOffsetMinutes(tz, utcMs);
  return `${pad(w.year, 4)}-${pad(w.month)}-${pad(w.day)}T${pad(w.hour)}:${pad(w.minute)}:${pad(w.second)}${formatOffset(off)}`;
}

/** datetime-local value in `tz` → ISO with offset (what the backend requires for events). */
export function zonedLocalToIso(local: string, tz: string): string {
  return utcMsToZonedIso(zonedLocalToUtcMs(local, tz), tz);
}

/** Any ISO instant → datetime-local value ("YYYY-MM-DDTHH:mm") as seen in `tz`. */
export function isoToZonedLocal(iso: string, tz: string): string {
  const w = wallParts(tz, Date.parse(iso));
  return `${pad(w.year, 4)}-${pad(w.month)}-${pad(w.day)}T${pad(w.hour)}:${pad(w.minute)}`;
}

// ---------------------------------------------------------------- display helpers

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** "HH:MM" (24 h) → "9:30 AM". */
export function to12h(hhmm: string): string {
  const [hs, ms] = hhmm.split(':');
  const h = Number(hs);
  const suffix = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${ms ?? '00'} ${suffix}`;
}

type DateInput = string | number | Date;

function toDate(v: DateInput): Date {
  if (v instanceof Date) return v;
  if (typeof v === 'number') return new Date(v < 1e12 ? v * 1000 : v); // epoch seconds or ms
  return new Date(v);
}

export function formatInZone(v: DateInput | null | undefined, tz?: string, opts?: Intl.DateTimeFormatOptions): string {
  if (v === null || v === undefined || v === '') return '—';
  const d = toDate(v);
  if (Number.isNaN(d.getTime())) return '—';
  try {
    return new Intl.DateTimeFormat('en-US', { timeZone: tz, ...(opts ?? { dateStyle: 'medium', timeStyle: 'short' }) }).format(d);
  } catch {
    return d.toLocaleString();
  }
}

export function formatTime(v: DateInput | null | undefined, tz?: string): string {
  return formatInZone(v, tz, { hour: 'numeric', minute: '2-digit' });
}

export function formatDayTime(v: DateInput | null | undefined, tz?: string): string {
  return formatInZone(v, tz, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/** Short timezone label for a zone, e.g. "EDT". */
export function zoneAbbr(tz: string, at: number = Date.now()): string {
  try {
    const p = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date(at));
    return p.find((x) => x.type === 'timeZoneName')?.value ?? tz;
  } catch {
    return tz;
  }
}

/** "3h 05m", "12m 04s", "45s". */
export function formatDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${pad(m)}m`;
  if (m > 0) return `${m}m ${pad(sec)}s`;
  return `${sec}s`;
}

/** "12s ago", "5m ago", "in 3h 10m". */
export function relativeTime(v: DateInput | null | undefined, nowMs: number = Date.now()): string {
  if (v === null || v === undefined) return 'never';
  const t = toDate(v).getTime();
  if (Number.isNaN(t)) return '—';
  const diff = t - nowMs;
  if (Math.abs(diff) < 1500) return 'just now';
  return diff < 0 ? `${formatDuration(-diff)} ago` : `in ${formatDuration(diff)}`;
}

export const COMMON_US_ZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'America/Puerto_Rico',
];

export function allTimeZones(): string[] {
  try {
    const fn = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
    if (fn) return fn('timeZone');
  } catch {
    /* fall through */
  }
  return [...COMMON_US_ZONES, 'UTC'];
}
