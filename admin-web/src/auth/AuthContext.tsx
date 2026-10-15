import { useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, api, setAuthHandlers, setCsrfToken } from '../api';
import type { AuthResponse, MfaState, SessionUser } from '../types';

export type AuthStatus = 'loading' | 'anonymous' | 'mfa' | 'ready';

interface AuthState {
  status: AuthStatus;
  user: SessionUser | null;
  mfa: MfaState | null;
}

interface AuthApi extends AuthState {
  isAdmin: boolean;
  /** Apply a login / me / mfa response. */
  accept: (r: AuthResponse) => void;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthApi | null>(null);

function stateFrom(r: AuthResponse): AuthState {
  return { status: r.mfa === 'ok' ? 'ready' : 'mfa', user: r.user, mfa: r.mfa };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [state, setState] = useState<AuthState>({ status: 'loading', user: null, mfa: null });

  const accept = useCallback((r: AuthResponse) => {
    setCsrfToken(r.csrf_token);
    setState(stateFrom(r));
  }, []);

  const toAnonymous = useCallback(() => {
    setCsrfToken(null);
    qc.clear();
    setState({ status: 'anonymous', user: null, mfa: null });
  }, [qc]);

  const refresh = useCallback(async () => {
    try {
      accept(await api.get<AuthResponse>('/api/auth/me', { noAuthRedirect: true }));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) toAnonymous();
      else setState((s) => (s.status === 'loading' ? { status: 'anonymous', user: null, mfa: null } : s));
    }
  }, [accept, toAnonymous]);

  useEffect(() => {
    setAuthHandlers({
      onUnauthorized: toAnonymous,
      onMfaRequired: () => {
        // Re-read the session to learn whether it is "required" or "setup_required".
        void refresh();
      },
    });
  }, [toAnonymous, refresh]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await api.post('/api/auth/logout', {}, { noAuthRedirect: true });
    } catch {
      /* session may already be gone */
    }
    toAnonymous();
  }, [toAnonymous]);

  const value = useMemo<AuthApi>(
    () => ({ ...state, isAdmin: state.user?.role === 'admin', accept, logout, refresh }),
    [state, accept, logout, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthApi {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside AuthProvider');
  return v;
}
