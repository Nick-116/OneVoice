export type Phase = "live" | "upcoming" | "ended" | "idle" | "unavailable";
export type CaptionState = "live" | "waiting" | "disconnected" | "unavailable";

export interface Language {
  code: string;
  name: string;
  rtl: boolean;
}

export interface ServiceInfo {
  key: string;
  name: string;
  start: string;
  end: string;
}

export interface NextService {
  name: string;
  start: string;
  window_start: string;
}

export interface CampusStatus {
  slug: string;
  name?: string;
  timezone?: string;
  source_language?: string;
  default_language?: string;
  phase: Phase;
  captions?: CaptionState | null;
  service?: ServiceInfo | null;
  next?: NextService | null;
  languages?: Language[];
  server_time: number;
}

export interface CampusSummary {
  slug: string;
  name: string;
}

export interface PublicConfig {
  church_name: string;
  campuses: CampusSummary[];
  theme?: Partial<Record<"50" | "100" | "500" | "600" | "700" | "800", string>> | null;
  logo_version?: string | null;
  fonts?: { body?: string; name?: string } | null;
}

export interface CaptionMessage {
  t: "caption";
  occ: string;
  id: number;
  final: boolean;
  lang: string;
  text: string;
  ts?: number;
  lat?: number;
}

export interface NoticeMessage {
  t: "notice";
  code: "translation_unavailable" | "translation_restored" | string;
  lang?: string;
}

export type StreamMessage = CaptionMessage | NoticeMessage;
