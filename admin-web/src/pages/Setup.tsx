import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Brand } from '../components/Brand';
import { Badge, Button, ErrorBox, Field, Input, Loading, Select } from '../components/ui';
import { useAction } from '../lib/queries';
import type { AuthResponse, Providers } from '../types';
import { ProviderForm, providersKey } from './Providers';

export interface SetupStatus {
  needs_admin: boolean;
  setup_complete: boolean;
}

export const setupKey = ['setup-status'] as const;

export function useSetupStatus() {
  return useQuery({ queryKey: setupKey, queryFn: () => api.get<SetupStatus>('/api/setup/status', { noAuthRedirect: true }) });
}

// ---------------------------------------------------------------- step 0: first administrator
export function FirstAdminPage() {
  const { accept } = useAuth();
  const qc = useQueryClient();
  const [code, setCode] = useState('');
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError('The passwords do not match.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const r = await api.post<AuthResponse>(
        '/api/setup/admin',
        { setup_code: code, username, display_name: displayName, password },
        { noAuthRedirect: true },
      );
      setPassword('');
      setConfirm('');
      await qc.invalidateQueries({ queryKey: setupKey });
      accept(r); // continues to two-factor enrolment
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SetupShell step={0} title="Welcome to OneVoice" subtitle="Let’s create the first administrator account.">
      <form onSubmit={submit} className="space-y-4">
        <Field
          label="Setup code"
          hint={
            <>
              Printed in the server log when OneVoice starts. On the server run{' '}
              <code className="rounded bg-gray-100 px-1">docker compose logs admin | grep "setup code"</code>
            </>
          }
        >
          {(id) => (
            <Input
              id={id}
              required
              autoFocus
              autoComplete="off"
              spellCheck={false}
              placeholder="ABCD-EFGH"
              className="font-mono uppercase tracking-widest"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Username">
            {(id) => <Input id={id} required autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />}
          </Field>
          <Field label="Your name (optional)">
            {(id) => <Input id={id} autoComplete="name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />}
          </Field>
        </div>
        <Field label="Password" hint="At least 12 characters. A passphrase works well.">
          {(id) => <Input id={id} type="password" required minLength={12} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        <Field label="Confirm password">
          {(id) => <Input id={id} type="password" required minLength={12} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />}
        </Field>
        {error && <ErrorBox error={error} />}
        <Button type="submit" variant="primary" className="w-full" loading={busy}>
          Create administrator
        </Button>
        <p className="text-center text-xs text-gray-500">Next you’ll set up two-factor sign-in with an authenticator app.</p>
      </form>
    </SetupShell>
  );
}

// ---------------------------------------------------------------- wizard shell
const STEPS = ['Administrator', 'Two-factor', 'Church', 'Speech-to-text', 'Translation', 'Done'];

export function SetupShell({ step, title, subtitle, children, wide }: { step: number; title: string; subtitle?: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-sky-50 px-4 py-10">
      <div className={wide ? 'mx-auto max-w-3xl' : 'mx-auto max-w-lg'}>
        <div className="mb-6 flex flex-col items-center gap-3">
          <Brand size="lg" />
          <ol className="flex flex-wrap justify-center gap-1.5 text-xs" aria-label="Setup progress">
            {STEPS.map((s, i) => (
              <li
                key={s}
                aria-current={i === step ? 'step' : undefined}
                className={
                  i < step
                    ? 'rounded-full bg-indigo-100 px-2.5 py-1 text-indigo-700'
                    : i === step
                      ? 'rounded-full bg-indigo-600 px-2.5 py-1 font-semibold text-white'
                      : 'rounded-full bg-white px-2.5 py-1 text-gray-500 ring-1 ring-gray-200'
                }
              >
                {i < step ? '✓ ' : ''}
                {s}
              </li>
            ))}
          </ol>
          <h1 className="mt-2 text-center text-2xl font-semibold text-gray-900">{title}</h1>
          {subtitle && <p className="text-center text-sm text-gray-600">{subtitle}</p>}
        </div>
        <div className="rounded-2xl border border-white/60 bg-white/80 p-6 shadow-xl shadow-indigo-100 backdrop-blur">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- steps 2-5
function ChurchStep({ onNext }: { onNext: () => void }) {
  const [name, setName] = useState('');
  const save = useAction((n: string) => api.put('/api/branding', { church_name: n }), { onSuccess: onNext });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) save.mutate(name.trim());
        else onNext();
      }}
      className="space-y-4"
    >
      <Field label="Church name" hint="Shown on the caption site. Logo, colors and fonts can be changed later under Branding.">
        {(id) => <Input id={id} autoFocus maxLength={120} placeholder="Grace Community Church" value={name} onChange={(e) => setName(e.target.value)} />}
      </Field>
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={save.isPending}>
          Continue
        </Button>
      </div>
    </form>
  );
}

function SttStep({ providers, onNext, onBack }: { providers: Providers; onNext: () => void; onBack: () => void }) {
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const test = useAction(() => api.post<{ ok: boolean; message: string }>('/api/setup/test-stt'), { onSuccess: (r) => setResult(r) });
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        OneVoice sends your speech mix to a speech-to-text service during scheduled services only. We tested with{' '}
        <strong>Deepgram</strong> (about $0.0077/minute; new accounts get free credit). AssemblyAI also works.
      </p>
      <ProviderForm key={JSON.stringify(providers.stt)} kind="stt" info={providers.stt} />
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => test.mutate()} loading={test.isPending}>
          Test saved key
        </Button>
        {result && <Badge tone={result.ok ? 'green' : 'red'}>{result.message}</Badge>}
      </div>
      <StepNav onBack={onBack} onNext={onNext} />
    </div>
  );
}

function TranslationStep({ providers, onNext, onBack }: { providers: Providers; onNext: () => void; onBack: () => void }) {
  const [target, setTarget] = useState('es');
  const [result, setResult] = useState('');
  const test = useAction(
    () => api.post<{ text: string; latency_ms: number }>('/api/languages/test', { text: 'Welcome, we are glad you are here today.', target }),
    { onSuccess: (r) => setResult(`${r.text} (${r.latency_ms} ms)`) },
  );
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        Captions are translated once per language that someone is actually reading. We tested with{' '}
        <strong>Azure AI Translator</strong> (nonprofits can get Azure credits through Microsoft for Nonprofits). Google Cloud Translation also works.
      </p>
      <ProviderForm key={JSON.stringify(providers.translation)} kind="translation" info={providers.translation} />
      <div className="flex flex-wrap items-center gap-3">
        <Select aria-label="Test language" value={target} onChange={(e) => setTarget(e.target.value)} className="w-40">
          <option value="es">Spanish</option>
          <option value="pt">Portuguese</option>
          <option value="fr">French</option>
          <option value="ht">Haitian Creole</option>
          <option value="zh">Chinese</option>
          <option value="ko">Korean</option>
        </Select>
        <Button onClick={() => test.mutate()} loading={test.isPending}>
          Test translation
        </Button>
      </div>
      {result && <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-900">{result}</p>}
      <StepNav onBack={onBack} onNext={onNext} />
    </div>
  );
}

function StepNav({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  return (
    <div className="flex justify-between border-t border-gray-100 pt-4">
      <Button onClick={onBack}>Back</Button>
      <Button variant="primary" onClick={onNext}>
        Continue
      </Button>
    </div>
  );
}

function DoneStep({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const finish = useAction(() => api.post('/api/setup/complete'), {
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: setupKey });
      navigate('/', { replace: true });
    },
  });
  return (
    <div className="space-y-4 text-sm text-gray-700">
      <p>You’re ready. Next steps in the dashboard:</p>
      <ol className="list-decimal space-y-1 ps-5">
        <li><strong>Campuses</strong>: add each campus and the languages it offers.</li>
        <li><strong>Services</strong>: enter your weekly service times.</li>
        <li><strong>Audio</strong>: create a sender token and paste it into the OneVoice Sender app at the church.</li>
        <li><strong>QR codes</strong>: print one per campus.</li>
        <li><strong>Branding</strong>: logo, button color and fonts.</li>
      </ol>
      <div className="flex justify-between border-t border-gray-100 pt-4">
        <Button onClick={onBack}>Back</Button>
        <Button variant="primary" onClick={() => finish.mutate()} loading={finish.isPending}>
          Go to the dashboard
        </Button>
      </div>
    </div>
  );
}

export function SetupWizardPage() {
  const [step, setStep] = useState(2);
  const providers = useQuery({ queryKey: providersKey, queryFn: () => api.get<Providers>('/api/providers') });
  const titles: Record<number, [string, string]> = {
    2: ['Your church', 'What should the caption site be called?'],
    3: ['Speech-to-text', 'Turns the pastor’s voice into live text.'],
    4: ['Translation', 'Turns the live text into other languages.'],
    5: ['All set', 'Setup is complete.'],
  };
  const [title, subtitle] = titles[step] ?? titles[2]!;
  const next = () => setStep((s) => Math.min(5, s + 1));
  const back = () => setStep((s) => Math.max(2, s - 1));
  return (
    <SetupShell step={step} title={title} subtitle={subtitle} wide={step === 3 || step === 4}>
      {providers.isPending ? (
        <Loading />
      ) : providers.isError ? (
        <ErrorBox error={providers.error} />
      ) : step === 2 ? (
        <ChurchStep onNext={next} />
      ) : step === 3 ? (
        <SttStep providers={providers.data} onNext={next} onBack={back} />
      ) : step === 4 ? (
        <TranslationStep providers={providers.data} onNext={next} onBack={back} />
      ) : (
        <DoneStep onBack={back} />
      )}
    </SetupShell>
  );
}

