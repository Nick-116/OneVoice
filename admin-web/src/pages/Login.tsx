import { useState, type FormEvent, type ReactNode } from 'react';
import { api, errorMessage } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Brand } from '../components/Brand';
import { Button, ErrorBox, Field, Input } from '../components/ui';
import type { AuthResponse } from '../types';

export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-50 via-white to-sky-50 px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2">
          <Brand size="lg" />
          <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
          {subtitle && <p className="text-center text-sm text-gray-500">{subtitle}</p>}
        </div>
        <div className="rounded-2xl border border-white/60 bg-white/80 p-6 shadow-xl shadow-indigo-100 backdrop-blur">{children}</div>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { accept } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const r = await api.post<AuthResponse>('/api/auth/login', { username, password }, { noAuthRedirect: true });
      setPassword('');
      accept(r);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Sign in" subtitle="Manage live captions and translation.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Username">
          {(id) => <Input id={id} autoComplete="username" autoFocus required value={username} onChange={(e) => setUsername(e.target.value)} />}
        </Field>
        <Field label="Password">
          {(id) => <Input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        {error && <ErrorBox error={error} />}
        <Button type="submit" variant="primary" className="w-full" loading={busy}>
          Sign in
        </Button>
      </form>
    </AuthShell>
  );
}
