import type { CaptionMessage, NoticeMessage } from "./types";

export const MAX_FINALS = 200;

export interface CaptionLine {
  id: number;
  text: string;
}

export interface CaptionState {
  occ: string | null;
  finals: CaptionLine[];
  partial: CaptionLine | null;
  translationUnavailable: boolean;
}

export type CaptionAction =
  | { type: "occ"; occ: string | null }
  | { type: "reset" }
  | { type: "caption"; message: CaptionMessage }
  | { type: "backlog"; messages: CaptionMessage[] }
  | { type: "notice"; message: NoticeMessage };

export const initialCaptionState: CaptionState = {
  occ: null,
  finals: [],
  partial: null,
  translationUnavailable: false,
};

function upsertFinal(finals: CaptionLine[], line: CaptionLine): CaptionLine[] {
  const last = finals[finals.length - 1];
  if (!last || line.id > last.id) {
    const next = [...finals, line];
    return next.length > MAX_FINALS ? next.slice(next.length - MAX_FINALS) : next;
  }
  const idx = finals.findIndex((f) => f.id >= line.id);
  const existing = finals[idx];
  if (existing && existing.id === line.id) {
    if (existing.text === line.text) return finals;
    const next = finals.slice();
    next[idx] = line;
    return next;
  }
  if (finals.length >= MAX_FINALS && idx === 0) return finals;
  const next = [...finals.slice(0, idx), line, ...finals.slice(idx)];
  return next.length > MAX_FINALS ? next.slice(next.length - MAX_FINALS) : next;
}

function applyCaption(state: CaptionState, msg: CaptionMessage): CaptionState {
  if (state.occ === null || msg.occ !== state.occ) return state;
  if (msg.final) {
    const finals = upsertFinal(state.finals, { id: msg.id, text: msg.text });
    const partial = state.partial && state.partial.id <= msg.id ? null : state.partial;
    if (finals === state.finals && partial === state.partial) return state;
    return { ...state, finals, partial };
  }
  if (msg.text === "") return state.partial ? { ...state, partial: null } : state;
  const last = state.finals[state.finals.length - 1];
  if (last && msg.id <= last.id) return state;
  return { ...state, partial: { id: msg.id, text: msg.text } };
}

export function captionReducer(state: CaptionState, action: CaptionAction): CaptionState {
  switch (action.type) {
    case "occ":
      if (action.occ === state.occ) return state;
      return { ...initialCaptionState, occ: action.occ };
    case "reset":
      return { ...initialCaptionState, occ: state.occ };
    case "caption":
      return applyCaption(state, action.message);
    case "backlog":
      return action.messages.reduce(
        (s, m) => (m.final ? applyCaption(s, m) : s),
        state,
      );
    case "notice":
      if (action.message.code === "translation_unavailable") {
        return state.translationUnavailable ? state : { ...state, translationUnavailable: true };
      }
      if (action.message.code === "translation_restored") {
        return state.translationUnavailable ? { ...state, translationUnavailable: false } : state;
      }
      return state;
  }
}
