import { describe, expect, it } from "vitest";
import { backoffMs, clockOffsetMs, countdownView, formatHms, MINUTE, nextPollDelay, SECOND } from "./time";
import type { CampusStatus } from "./types";

describe("countdown math", () => {
  it("says 'about to begin' under one minute, including overdue", () => {
    expect(countdownView(59_999)).toEqual({ kind: "soon" });
    expect(countdownView(-5000)).toEqual({ kind: "soon" });
  });

  it("rounds minutes up below one hour", () => {
    expect(countdownView(MINUTE)).toEqual({ kind: "minutes", minutes: 1 });
    expect(countdownView(MINUTE + 1)).toEqual({ kind: "minutes", minutes: 2 });
    expect(countdownView(59 * MINUTE + 30 * SECOND)).toEqual({ kind: "minutes", minutes: 60 });
  });

  it("shows HH:MM:SS from one hour", () => {
    expect(countdownView(60 * MINUTE)).toEqual({ kind: "far", hms: "01:00:00" });
    expect(formatHms(26 * 3600 * 1000 + 3 * MINUTE + 9 * SECOND + 999)).toBe("26:03:09");
  });

  it("computes the server clock offset", () => {
    expect(clockOffsetMs(1_760_000_010.5, 1_760_000_000_000)).toBe(10_500);
  });
});

describe("backoff", () => {
  it("grows exponentially, is capped, and jitters within [ceiling/2, ceiling]", () => {
    expect(backoffMs(0, 1000, 15_000, 0)).toBe(500);
    expect(backoffMs(0, 1000, 15_000, 1)).toBe(1000);
    expect(backoffMs(3, 1000, 15_000, 1)).toBe(8000);
    expect(backoffMs(10, 1000, 15_000, 1)).toBe(15_000);
  });
});

describe("nextPollDelay", () => {
  const now = Date.parse("2026-10-18T13:00:00Z");
  const base = (over: Partial<CampusStatus>): CampusStatus => ({ slug: "x", phase: "idle", server_time: now / 1000, ...over });
  const input = { failures: 0, retryAfterMs: 0, streaming: false, serverNowMs: now, random: 0 };

  it("polls upcoming every 30 s, then right at the window start, then every ~3 s", () => {
    const far = base({ phase: "upcoming", next: { name: "", start: "2026-10-18T14:00:00Z", window_start: "2026-10-18T13:45:00Z" } });
    expect(nextPollDelay({ ...input, status: far })).toBe(30 * SECOND);
    const near = base({ phase: "upcoming", next: { name: "", start: "2026-10-18T13:15:00Z", window_start: "2026-10-18T13:00:10Z" } });
    expect(nextPollDelay({ ...input, status: near })).toBe(10_250);
    const open = base({ phase: "upcoming", next: { name: "", start: "2026-10-18T13:15:00Z", window_start: "2026-10-18T12:59:00Z" } });
    expect(nextPollDelay({ ...input, status: open })).toBe(2500);
  });

  it("polls ended/idle every 60 s and stops while streaming live", () => {
    expect(nextPollDelay({ ...input, status: base({ phase: "ended" }) })).toBe(60 * SECOND);
    expect(nextPollDelay({ ...input, status: base({ phase: "live" }), streaming: true })).toBeNull();
  });

  it("backs off on failures and honours Retry-After", () => {
    expect(nextPollDelay({ ...input, status: null, failures: 1, random: 1 })).toBe(2000);
    expect(nextPollDelay({ ...input, status: null, failures: 6, random: 1 })).toBe(30_000);
    expect(nextPollDelay({ ...input, status: null, failures: 1, retryAfterMs: 10_000 })).toBe(10_000);
  });
});
