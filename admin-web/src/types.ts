// Typed models for the admin API (docs/API.md section 2, backend/captions/admin/*).

export type Role = 'admin' | 'operator';
export type MfaState = 'ok' | 'required' | 'setup_required';

export interface SessionUser {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  mfa_enabled: boolean;
}

export interface AuthResponse {
  user: SessionUser;
  mfa: MfaState;
  csrf_token: string;
}

export interface MfaSetupResponse {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

export interface OkResponse {
  ok: boolean;
}

// ---------------------------------------------------------------- campuses
export interface Campus {
  id: number;
  slug: string;
  name: string;
  timezone: string;
  source_language: string;
  default_language: string;
  enabled: boolean;
  retain_transcripts: boolean;
  languages: string[];
}

export interface CampusInput {
  slug: string;
  name: string;
  timezone: string;
  source_language: string;
  default_language: string;
  enabled: boolean;
  retain_transcripts: boolean;
  languages: string[];
}

export type Phase = 'live' | 'upcoming' | 'ended' | 'idle';
export type CaptionState = 'live' | 'waiting' | 'disconnected' | 'unavailable';

export interface ServiceRef {
  key: string;
  name: string;
  start: string;
  end: string;
}

export interface NextServiceRef {
  name: string;
  start: string;
  window_start: string;
}

export interface LatencySummary {
  p50: number | null;
  p95: number | null;
  n: number;
}

export interface PipelineMetrics {
  stt_partial_ms: LatencySummary;
  stt_final_ms: LatencySummary;
  translate_ms: Record<string, LatencySummary>;
  end_to_end_ms: Record<string, LatencySummary>;
}

export type SttState = 'idle' | 'connecting' | 'connected' | 'error';

export interface PipelineStatus {
  occurrence: string;
  stt: SttState;
  stt_error: string | null;
  stt_error_since?: number | null;
  stt_connected_since: number | null;
  first_result_at: number | null;
  last_caption_at: number | null;
  segments: number;
  translation: Record<string, string>;
  metrics: PipelineMetrics;
}

export interface CampusStatus {
  phase: Phase;
  captions: CaptionState | null;
  service: ServiceRef | null;
  next: NextServiceRef | null;
  viewers: Record<string, number>;
  pipeline: PipelineStatus | null;
  stt_provider: string;
  stt_configured: boolean;
  translation_provider: string;
  translation_configured: boolean;
  updated: number;
}

export interface AudioStatus {
  connected: boolean;
  sender_name: string | null;
  remote_ip: string | null;
  connected_at: number | null;
  disconnected_at: number | null;
  last_frame_at: number | null;
  last_signal_at: number | null;
  level_dbfs: number | null;
  peak_dbfs: number | null;
  sample_rate: number | null;
  format: string | null;
  forwarding: boolean;
  bytes: number | null;
}

export interface ErrorEntry {
  at: number;
  component: string;
  campus_id: number | null;
  message: string;
}

export interface UsageMonth {
  stt_minutes: number;
  translation_chars: number;
  est_cost_usd: number;
}

export interface OverviewCampus {
  campus: Campus;
  status: CampusStatus | null;
  audio: AudioStatus;
}

export interface Overview {
  worker: { alive: boolean; heartbeat: number | null };
  campuses: OverviewCampus[];
  recent_errors: ErrorEntry[];
  usage_month: UsageMonth;
  server_time: number;
}

export interface AudioHistoryEntry {
  at: number;
  event: 'connected' | 'disconnected' | string;
  sender?: string;
  ip?: string;
  reason?: string;
  duration?: number;
}

export interface AudioCampus {
  campus: Campus;
  audio: AudioStatus;
  history: AudioHistoryEntry[];
}

// ---------------------------------------------------------------- schedules
export interface Schedule {
  id: number;
  campus_id: number;
  name: string;
  weekday: number; // 0 = Monday … 6 = Sunday
  start_time: string; // HH:MM
  end_time: string;
  timezone: string;
  enabled: boolean;
  early_access_minutes: number;
  languages: string[] | null;
  valid_from: string | null;
  valid_until: string | null;
}

export type ScheduleInput = Omit<Schedule, 'id'>;

export type EventKind = 'special' | 'holiday' | 'manual';

export interface ServiceEvent {
  id: number;
  campus_id: number;
  name: string;
  kind: EventKind;
  start_at: string;
  end_at: string;
  early_access_minutes: number;
  cancelled: boolean;
  languages: string[] | null;
}

export type OccurrenceKind = 'recurring' | 'special' | 'holiday' | 'manual';

export interface Occurrence {
  key: string;
  campus_id: number;
  name: string;
  kind: OccurrenceKind;
  start: string;
  end: string;
  window_start: string;
  cancelled: boolean;
  schedule_id: number | null;
  event_id: number | null;
  local_date: string | null;
}

// ---------------------------------------------------------------- languages
export interface Language {
  code: string;
  name_en: string;
  native_name: string;
  rtl: boolean;
  enabled: boolean;
  sort_order: number;
  provider_codes: Record<string, string>;
  provider_supported: boolean;
  builtin: boolean;
  viewers: number;
}

export interface LanguageInput {
  code: string;
  name_en: string;
  native_name: string;
  rtl: boolean;
  enabled: boolean;
  sort_order: number;
}

export interface TranslateTestResult {
  provider: string;
  text: string;
  latency_ms: number;
}

// ---------------------------------------------------------------- providers & settings
export type ProviderKind = 'stt' | 'translation';
export type ProviderSettingValue = string | number | boolean | string[];
export type ProviderSettings = Record<string, ProviderSettingValue>;

export interface ProviderInfo {
  provider: string;
  settings: ProviderSettings;
  has_key: boolean;
  options: Record<string, ProviderSettings>;
}

export interface Providers {
  stt: ProviderInfo;
  translation: ProviderInfo;
}

export interface ProviderUpdate {
  provider: string;
  settings: ProviderSettings;
  api_key?: string;
  clear_key?: boolean;
}

export interface GeneralSettings {
  accent_color: string;
  church_name: string;
  public_base_url: string;
  effective_public_base_url?: string;
  manual_default_minutes: number;
  ended_grace_minutes: number;
  lookahead_days: number;
  transcript_retention_days: number;
  translate_partials: boolean;
  partial_min_interval_ms: number;
  language_grace_seconds: number;
  audio_timeout_seconds: number;
  digital_silence_seconds: number;
}

// ---------------------------------------------------------------- senders & users
export interface Sender {
  id: string;
  campus_id: number;
  name: string;
  allowed_cidrs: string[];
  created_at: string | null;
  revoked_at: string | null;
}

export interface SenderCreated extends Sender {
  token: string;
}

export interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  mfa_enabled: boolean;
  disabled: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

export interface UserPatch {
  display_name?: string;
  role?: Role;
  disabled?: boolean;
  password?: string;
  reset_mfa?: boolean;
}

// ---------------------------------------------------------------- usage, audit, transcripts
export type UsageMetric = 'stt_seconds' | 'translation_chars';

export interface UsageRow {
  day: string;
  campus_id: number;
  provider: string;
  metric: UsageMetric;
  language: string;
  quantity: number;
  est_cost_usd: number;
}

export interface Usage {
  days: number;
  month: UsageMonth;
  rows: UsageRow[];
}

export interface AuditEntry {
  at: string;
  username: string;
  action: string;
  target: string;
  details: Record<string, unknown> | null;
  ip: string | null;
}

export interface TranscriptEntry {
  occurrence: string;
  language: string;
  segments: number;
  started: string | null;
}

export interface QrLink {
  campus_id: number;
  slug: string;
  name: string;
  url: string;
}

/** FastAPI error body. */
export interface ValidationIssue {
  loc?: (string | number)[];
  msg: string;
  type?: string;
}

export type ErrorDetail = string | ValidationIssue[];

// ---------------------------------------------------------------- branding & updates
export type PaletteShade = '50' | '100' | '500' | '600' | '700' | '800';

export interface Branding {
  church_name: string;
  accent_color: string;
  palette: Record<PaletteShade, string>;
  contrast: Partial<Record<PaletteShade, number>>;
  logo: { sha256: string; updated_at: string | null; bytes: number } | null;
}

export interface UpdateCommit {
  sha: string;
  subject: string;
  author: string;
  date: string;
}

export interface UpdaterStatus {
  state?: 'idle' | 'checking' | 'updating' | 'rolling_back' | 'failed';
  message?: string;
  heartbeat?: string;
  branch?: string;
  checked_at?: string;
  current_commit?: string;
  current_version?: string;
  latest_commit?: string;
  behind?: number;
  commits?: UpdateCommit[];
  blocked?: string | null;
  started_at?: string;
  finished_at?: string;
  last_success?: string;
}

export interface UpdatesState {
  installed: { version: string; commit: string; built_at: string | null };
  updater_online: boolean;
  updater_installed: boolean;
  status: UpdaterStatus | null;
  pending_request: boolean;
  log: string[];
}
