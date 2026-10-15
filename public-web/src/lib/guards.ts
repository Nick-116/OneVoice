import type { CampusStatus, CaptionMessage, NoticeMessage, PublicConfig } from "./types";

const PHASES = new Set(["live", "upcoming", "ended", "idle", "unavailable"]);

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}

export function isCampusStatus(v: unknown): v is CampusStatus {
  return (
    isRecord(v) &&
    typeof v.slug === "string" &&
    typeof v.phase === "string" &&
    PHASES.has(v.phase) &&
    typeof v.server_time === "number" &&
    (v.languages === undefined || Array.isArray(v.languages))
  );
}

export function isPublicConfig(v: unknown): v is PublicConfig {
  return isRecord(v) && Array.isArray(v.campuses);
}

export function isCaptionMessage(v: unknown): v is CaptionMessage {
  return (
    isRecord(v) &&
    v.t === "caption" &&
    typeof v.occ === "string" &&
    typeof v.id === "number" &&
    typeof v.final === "boolean" &&
    typeof v.text === "string"
  );
}

export function isNoticeMessage(v: unknown): v is NoticeMessage {
  return isRecord(v) && v.t === "notice" && typeof v.code === "string";
}
