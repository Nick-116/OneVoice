import { describe, expect, it } from "vitest";
import { captionReducer, initialCaptionState, MAX_FINALS, type CaptionState } from "./captions";
import type { CaptionMessage } from "./types";

const OCC = "r3-2026-10-18";

function cap(id: number, text: string, final: boolean, occ = OCC): CaptionMessage {
  return { t: "caption", occ, id, final, lang: "es", text };
}

function withOcc(): CaptionState {
  return captionReducer(initialCaptionState, { type: "occ", occ: OCC });
}

function feed(state: CaptionState, ...messages: CaptionMessage[]): CaptionState {
  return messages.reduce((s, message) => captionReducer(s, { type: "caption", message }), state);
}

describe("captionReducer", () => {
  it("ignores captions before the service key is known", () => {
    const s = feed(initialCaptionState, cap(1, "hola", true));
    expect(s.finals).toEqual([]);
  });

  it("ignores captions from another occurrence", () => {
    const s = feed(withOcc(), cap(1, "hola", true, "other"));
    expect(s.finals).toEqual([]);
  });

  it("replaces a partial with newer partials and then its final", () => {
    let s = feed(withOcc(), cap(1, "ho", false), cap(1, "hola a", false));
    expect(s.partial).toEqual({ id: 1, text: "hola a" });
    s = feed(s, cap(1, "Hola a todos.", true));
    expect(s.partial).toBeNull();
    expect(s.finals).toEqual([{ id: 1, text: "Hola a todos." }]);
  });

  it("keeps a newer partial when an older final arrives", () => {
    const s = feed(withOcc(), cap(2, "bien", false), cap(1, "Hola.", true));
    expect(s.partial).toEqual({ id: 2, text: "bien" });
    expect(s.finals.map((f) => f.id)).toEqual([1]);
  });

  it("clears the partial on empty text", () => {
    const s = feed(withOcc(), cap(3, "algo", false), cap(3, "", false));
    expect(s.partial).toBeNull();
  });

  it("ignores partials for already finalised segments", () => {
    const s = feed(withOcc(), cap(4, "Final.", true), cap(4, "late partial", false));
    expect(s.partial).toBeNull();
  });

  it("de-duplicates the backlog by id and keeps order", () => {
    let s = feed(withOcc(), cap(5, "cinco", true));
    s = captionReducer(s, {
      type: "backlog",
      messages: [cap(3, "tres", true), cap(4, "cuatro", true), cap(5, "cinco", true)],
    });
    expect(s.finals.map((f) => f.id)).toEqual([3, 4, 5]);
  });

  it("resets when the service key changes", () => {
    let s = feed(withOcc(), cap(1, "uno", true), cap(2, "dos", false));
    s = captionReducer(s, { type: "notice", message: { t: "notice", code: "translation_unavailable" } });
    s = captionReducer(s, { type: "occ", occ: "r3-2026-10-25" });
    expect(s).toEqual({ ...initialCaptionState, occ: "r3-2026-10-25" });
    expect(captionReducer(s, { type: "occ", occ: "r3-2026-10-25" })).toBe(s);
  });

  it("caps the number of finals", () => {
    let s = withOcc();
    for (let i = 1; i <= MAX_FINALS + 25; i++) s = feed(s, cap(i, `line ${i}`, true));
    expect(s.finals).toHaveLength(MAX_FINALS);
    expect(s.finals[0]?.id).toBe(26);
    expect(s.finals[MAX_FINALS - 1]?.id).toBe(MAX_FINALS + 25);
  });

  it("toggles the translation notice", () => {
    let s = captionReducer(withOcc(), { type: "notice", message: { t: "notice", code: "translation_unavailable" } });
    expect(s.translationUnavailable).toBe(true);
    s = captionReducer(s, { type: "notice", message: { t: "notice", code: "translation_restored" } });
    expect(s.translationUnavailable).toBe(false);
  });
});
