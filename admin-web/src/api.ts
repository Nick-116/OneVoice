// Single HTTP client for the admin API.
//
// * Cookie session: every request uses credentials 'same-origin'.
// * CSRF: the token lives in memory only (never localStorage). It is captured from any
//   response carrying `csrf_token` (login, /auth/me, mfa verify/enable — it rotates after MFA)
//   and sent as `X-CSRF-Token` on every non-GET request.
// * 401 → onUnauthorized (show login); 403 "Multi-factor authentication required" → onMfaRequired.

import type { ErrorDetail, ValidationIssue } from './types';

export const MFA_REQUIRED_DETAIL = 'Multi-factor authentication required';

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

export interface AuthHandlers {
  onUnauthorized: () => void;
  onMfaRequired: () => void;
}

let handlers: AuthHandlers = { onUnauthorized: () => {}, onMfaRequired: () => {} };

export function setAuthHandlers(h: AuthHandlers): void {
  handlers = h;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: ErrorDetail | null;

  constructor(status: number, detail: ErrorDetail | null) {
    super(formatDetail(detail) || `Request failed (HTTP ${status})`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function isIssueArray(v: unknown): v is ValidationIssue[] {
  return Array.isArray(v) && v.every((i) => typeof i === 'object' && i !== null && 'msg' in i);
}

/** Turn a FastAPI `detail` (string or 422 array of {loc,msg}) into readable text. */
export function formatDetail(detail: unknown): string {
  if (detail == null) return '';
  if (typeof detail === 'string') return detail;
  if (isIssueArray(detail)) {
    return detail
      .map((i) => {
        const loc = (i.loc ?? []).filter((p) => p !== 'body' && p !== 'query' && p !== 'path');
        const msg = i.msg.replace(/^Value error, /, '');
        return loc.length ? `${loc.join('.')}: ${msg}` : msg;
      })
      .join('; ');
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export interface RequestOptions {
  /** Skip the global 401/403-MFA handlers (used by the login and MFA screens themselves). */
  noAuthRedirect?: boolean;
  signal?: AbortSignal;
}

const SAFE = new Set(['GET', 'HEAD']);

export async function request<T>(method: string, path: string, body?: unknown, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const m = method.toUpperCase();
  const raw = body instanceof Blob;
  if (body !== undefined) headers['Content-Type'] = raw ? body.type || 'application/octet-stream' : 'application/json';
  if (!SAFE.has(m) && csrfToken) headers['X-CSRF-Token'] = csrfToken;

  const res = await fetch(path, {
    method: m,
    headers,
    body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
    credentials: 'same-origin',
    cache: 'no-store',
    signal: opts.signal,
  });

  let data: unknown = null;
  const ctype = res.headers.get('content-type') ?? '';
  if (ctype.includes('application/json')) {
    try {
      data = await res.json();
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const detail = (data && typeof data === 'object' && 'detail' in data ? (data as { detail: ErrorDetail }).detail : null) ?? null;
    if (!opts.noAuthRedirect) {
      if (res.status === 401) {
        csrfToken = null;
        handlers.onUnauthorized();
      } else if (res.status === 403 && detail === MFA_REQUIRED_DETAIL) {
        handlers.onMfaRequired();
      }
    }
    throw new ApiError(res.status, detail);
  }

  if (data && typeof data === 'object' && 'csrf_token' in data) {
    const t = (data as { csrf_token: unknown }).csrf_token;
    if (typeof t === 'string' && t) csrfToken = t;
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>('GET', path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('POST', path, body ?? {}, opts),
  put: <T>(path: string, body: unknown, opts?: RequestOptions) => request<T>('PUT', path, body, opts),
  patch: <T>(path: string, body: unknown, opts?: RequestOptions) => request<T>('PATCH', path, body, opts),
  del: <T>(path: string, opts?: RequestOptions) => request<T>('DELETE', path, undefined, opts),
  /** PUT a file as the raw request body; Content-Type comes from the Blob's type. */
  upload: <T>(path: string, file: Blob, opts?: RequestOptions) => request<T>('PUT', path, file, opts),
};

/** Build a query string from defined values. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : '';
}
