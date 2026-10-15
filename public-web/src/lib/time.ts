import type { CampusStatus } from "./types";

export const SECOND = 1000;
export const MINUTE = 60 * SECOND;

export function clockOffsetMs(serverTimeSec: number, localNowMs: number): number {
  return serverTimeSec * 1000 - localNowMs;
}

export function parseIsoMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const v = Date.parse(iso);
  return Number.isNaN(v) ? null : v;
}

export type CountdownView =
  | { kind: "soon" }
  | { kind: "minutes"; minutes: number }
  | { kind: "far"; hms: string };

export function countdownView(remainingMs: number): CountdownView {
  if (remainingMs < MINUTE) return { kind: "soon" };
  if (remainingMs < 60 * MINUTE) return { kind: "minutes", minutes: Math.ceil(remainingMs / MINUTE) };
  return { kind: "far", hms: formatHms(remainingMs) };
}

export function formatHms(ms: number): string {
  const total = Math.max(0, Math.floor(ms / SECOND));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

export function backoffMs(attempt: number, baseMs: number, maxMs: number, random: number): number {
  const ceiling = Math.min(maxMs, baseMs * 2 ** Math.max(0, attempt));
  return Math.round(ceiling / 2 + (ceiling / 2) * random);
}

export interface PollInput {
  status: CampusStatus | null;
  failures: number;
  retryAfterMs: number;
  streaming: boolean;
  serverNowMs: number;
  random: number;
}

export function nextPollDelay(p: PollInput): number | null {
  if (p.streaming && p.status?.phase === "live") return null;
  if (p.failures > 0 || !p.status || p.status.phase === "unavailable") {
    return Math.max(p.retryAfterMs, backoffMs(p.failures - 1, 2 * SECOND, 30 * SECOND, p.random));
  }
  switch (p.status.phase) {
    case "upcoming": {
      const windowStart = parseIsoMs(p.status.next?.window_start);
      if (windowStart === null) return 30 * SECOND;
      const until = windowStart - p.serverNowMs;
      if (until <= 0) return 2500 + Math.round(1000 * p.random);
      return Math.min(30 * SECOND, until + 250 + Math.round(750 * p.random));
    }
    case "ended":
    case "idle":
      return 60 * SECOND;
    default:
      return 30 * SECOND;
  }
}
