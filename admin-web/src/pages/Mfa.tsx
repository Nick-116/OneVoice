import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { api, errorMessage } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Button, CopyButton, ErrorBox, Field, Input, Loading } from '../components/ui';
import type { AuthResponse, MfaSetupResponse } from '../types';
import { AuthShell } from './Login';

function CodeForm({ onSubmit, busy, error, label }: { onSubmit: (code: string) => void; busy: boolean; error: string; label: string }) {
  const [code, setCode] = useState('');
  function submit(e: FormEvent) {
    e.preventDefault();
    if (/^\d{6}$/.test(code)) onSubmit(code);
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="6-digit code">
        {(id) => (
          <Input
            id={id}
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            autoFocus
            required
            className="text-center font-mono text-lg tracking-[0.5em]"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
          />
        )}
      </Field>
      {error && <ErrorBox error={error} />}
      <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={code.length !== 6}>
        {label}
      </Button>
    </form>
  );
}

function Enrol() {
  const { accept } = useAuth();
  const [setup, setSetup] = useState<MfaSetupResponse | null>(null);
  const [setupError, setSetupError] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const started = useRef(false);

  const start = useCallback(async () => {
    setSetupError('');
    setSetup(null);
    try {
      setSetup(await api.post<MfaSetupResponse>('/api/auth/mfa/setup', {}, { noAuthRedirect: true }));
    } catch (e) {
      setSetupError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    if (started.current) return; // guard StrictMode double effects: each call issues a new secret
    started.current = true;
    void start();
  }, [start]);

  async function enable(code: string) {
    setBusy(true);
    setError('');
    try {
      accept(await api.post<AuthResponse>('/api/auth/mfa/enable', { code }, { noAuthRedirect: true }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (setupError) {
    return (
      <div className="space-y-3">
        <ErrorBox error={setupError} />
        <Button onClick={() => void start()}>Try again</Button>
      </div>
    );
  }
  if (!setup) return <Loading label="Preparing enrolment…" />;
  return (
    <div className="space-y-4">
      <ol className="list-decimal space-y-1 pl-5 text-sm text-gray-600">
        <li>Open an authenticator app (1Password, Google Authenticator, Authy…).</li>
        <li>Scan this QR code, or enter the secret manually.</li>
        <li>Enter the 6-digit code it shows.</li>
      </ol>
      <div className="flex justify-center">
        <img
          src={'data:image/svg+xml;utf8,' + encodeURIComponent(setup.qr_svg)}
          alt="Authenticator enrolment QR code"
          className="h-48 w-48 rounded border border-gray-200 bg-white p-2"
        />
      </div>
      <div className="flex items-center gap-2 rounded-md bg-gray-50 p-2">
        <code className="flex-1 break-all font-mono text-xs text-gray-800">{setup.secret}</code>
        <CopyButton text={setup.secret} />
      </div>
      <CodeForm onSubmit={(c) => void enable(c)} busy={busy} error={error} label="Enable two-factor authentication" />
    </div>
  );
}

function Verify() {
  const { accept } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function verify(code: string) {
    setBusy(true);
    setError('');
    try {
      accept(await api.post<AuthResponse>('/api/auth/mfa/verify', { code }, { noAuthRedirect: true }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return <CodeForm onSubmit={(c) => void verify(c)} busy={busy} error={error} label="Verify" />;
}

export function MfaPage() {
  const { mfa, user, logout } = useAuth();
  const enrol = mfa === 'setup_required';
  return (
    <AuthShell
      title={enrol ? 'Set up two-factor authentication' : 'Two-factor authentication'}
      subtitle={enrol ? 'Required for every admin account.' : `Enter the code from your authenticator app${user ? ` for ${user.username}` : ''}.`}
    >
      {enrol ? <Enrol /> : <Verify />}
      <div className="mt-4 text-center">
        <button type="button" className="text-sm text-gray-500 hover:text-gray-800 hover:underline" onClick={() => void logout()}>
          Sign in as someone else
        </button>
      </div>
    </AuthShell>
  );
}
