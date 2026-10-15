import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, formatDetail, getCsrfToken, setAuthHandlers, setCsrfToken } from './api';

interface Call {
  url: string;
  init: RequestInit;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

let calls: Call[];
let next: Response[];

beforeEach(() => {
  calls = [];
  next = [];
  setCsrfToken(null);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return next.shift() ?? jsonResponse(200, { ok: true });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthHandlers({ onUnauthorized: () => {}, onMfaRequired: () => {} });
});

const header = (c: Call | undefined, name: string) => (c?.init.headers as Record<string, string> | undefined)?.[name];

describe('api client CSRF handling', () => {
  it('captures csrf_token from login and sends it on non-GET requests only', async () => {
    next.push(jsonResponse(200, { user: { id: 1 }, mfa: 'required', csrf_token: 'tok-1' }));
    await api.post('/api/auth/login', { username: 'a', password: 'b' }, { noAuthRedirect: true });
    expect(getCsrfToken()).toBe('tok-1');
    expect(header(calls[0], 'X-CSRF-Token')).toBeUndefined();

    await api.get('/api/overview');
    expect(header(calls[1], 'X-CSRF-Token')).toBeUndefined();

    await api.post('/api/campuses/1/stop');
    expect(header(calls[2], 'X-CSRF-Token')).toBe('tok-1');
    await api.patch('/api/users/2', { role: 'admin' });
    expect(header(calls[3], 'X-CSRF-Token')).toBe('tok-1');
    await api.del('/api/users/2');
    expect(header(calls[4], 'X-CSRF-Token')).toBe('tok-1');
  });

  it('uses the rotated token after MFA verification', async () => {
    setCsrfToken('before-mfa');
    next.push(jsonResponse(200, { user: { id: 1 }, mfa: 'ok', csrf_token: 'after-mfa' }));
    await api.post('/api/auth/mfa/verify', { code: '123456' }, { noAuthRedirect: true });
    expect(header(calls[0], 'X-CSRF-Token')).toBe('before-mfa');
    await api.put('/api/settings', { lookahead_days: 7 });
    expect(header(calls[1], 'X-CSRF-Token')).toBe('after-mfa');
  });

  it('always sends cookies same-origin and JSON bodies', async () => {
    await api.post('/api/occurrences/cancel', { key: 'e1' });
    expect(calls[0]?.init.credentials).toBe('same-origin');
    expect(header(calls[0], 'Content-Type')).toBe('application/json');
    expect(calls[0]?.init.body).toBe('{"key":"e1"}');
  });
});

describe('api client error handling', () => {
  it('401 clears the token and calls onUnauthorized', async () => {
    const onUnauthorized = vi.fn();
    const onMfaRequired = vi.fn();
    setAuthHandlers({ onUnauthorized, onMfaRequired });
    setCsrfToken('tok');
    next.push(jsonResponse(401, { detail: 'Session expired' }));
    await expect(api.get('/api/overview')).rejects.toMatchObject({ status: 401, message: 'Session expired' });
    expect(onUnauthorized).toHaveBeenCalledOnce();
    expect(onMfaRequired).not.toHaveBeenCalled();
    expect(getCsrfToken()).toBeNull();
  });

  it('403 MFA required calls onMfaRequired, other 403s do not', async () => {
    const onMfaRequired = vi.fn();
    setAuthHandlers({ onUnauthorized: vi.fn(), onMfaRequired });
    next.push(jsonResponse(403, { detail: 'Multi-factor authentication required' }));
    await expect(api.get('/api/overview')).rejects.toBeInstanceOf(ApiError);
    expect(onMfaRequired).toHaveBeenCalledOnce();
    next.push(jsonResponse(403, { detail: 'Administrator role required' }));
    await expect(api.get('/api/users')).rejects.toThrow('Administrator role required');
    expect(onMfaRequired).toHaveBeenCalledOnce();
  });

  it('noAuthRedirect suppresses the global handlers (bad password on login)', async () => {
    const onUnauthorized = vi.fn();
    setAuthHandlers({ onUnauthorized, onMfaRequired: vi.fn() });
    next.push(jsonResponse(401, { detail: 'Invalid username or password' }));
    await expect(api.post('/api/auth/login', {}, { noAuthRedirect: true })).rejects.toThrow('Invalid username or password');
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it('formats 422 validation arrays', async () => {
    next.push(
      jsonResponse(422, {
        detail: [{ loc: ['body', 'password'], msg: 'String should have at least 12 characters', type: 'string_too_short' }],
      }),
    );
    await expect(api.post('/api/users', {})).rejects.toThrow('password: String should have at least 12 characters');
    expect(formatDetail([{ loc: ['body'], msg: 'Value error, end_at must be after start_at' }])).toBe(
      'end_at must be after start_at',
    );
  });
});

describe('file uploads', () => {
  it('sends the raw file with its content type and the CSRF token', async () => {
    setCsrfToken('tok-up');
    const file = new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: 'image/png' });
    await api.upload('/api/branding/logo', file);
    expect(calls[0]?.init.method).toBe('PUT');
    expect(header(calls[0], 'Content-Type')).toBe('image/png');
    expect(header(calls[0], 'X-CSRF-Token')).toBe('tok-up');
    expect(calls[0]?.init.body).toBe(file);
  });
});
