import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { api } from '../api';
import { Badge, Button, Card, Checkbox, ErrorBox, Field, Input, Loading, PageHeader, Select, Textarea, Toggle } from '../components/ui';
import { keys, useAction, useSettings } from '../lib/queries';
import type { GeneralSettings, ProviderInfo, ProviderKind, Providers, ProviderSettings, ProviderSettingValue, ProviderUpdate } from '../types';

const providersKey = ['providers'] as const;

const PROVIDER_LABELS: Record<string, string> = {
  deepgram: 'Deepgram',
  assemblyai: 'AssemblyAI',
  azure: 'Azure Translator',
  google: 'Google Cloud Translation',
  simulated: 'Simulated (testing only)',
};

const SETTING_LABELS: Record<string, [string, string?]> = {
  model: ['Model'],
  endpointing_ms: ['Endpointing (ms)', 'Silence before a phrase is finalised.'],
  keyterms: ['Key terms', 'One per line: names, places and church vocabulary to boost recognition.'],
  price_per_minute: ['Price per minute (USD)', 'Used for cost estimates only.'],
  words_per_minute: ['Simulated words per minute'],
  region: ['Region'],
  endpoint: ['Endpoint'],
  price_per_million_chars: ['Price per million characters (USD)', 'Used for cost estimates only.'],
  fail_languages: ['Simulate failures for languages', 'Language codes, one per line.'],
  delay_ms: ['Simulated delay (ms)'],
};

function SettingInput({ name, value, onChange }: { name: string; value: ProviderSettingValue; onChange: (v: ProviderSettingValue) => void }) {
  const [label, hint] = SETTING_LABELS[name] ?? [name.replace(/_/g, ' ')];
  if (Array.isArray(value)) {
    return (
      <Field label={label} hint={hint} className="sm:col-span-2">
        {(id) => (
          <Textarea
            id={id}
            rows={4}
            value={value.join('\n')}
            onChange={(e) => onChange(e.target.value.split('\n'))}
          />
        )}
      </Field>
    );
  }
  if (typeof value === 'boolean') return <Toggle checked={value} onChange={onChange} label={label} />;
  if (typeof value === 'number') {
    return (
      <Field label={label} hint={hint}>
        {(id) => <Input id={id} type="number" step="any" value={Number.isFinite(value) ? value : ''} onChange={(e) => onChange(e.target.value === '' ? NaN : Number(e.target.value))} />}
      </Field>
    );
  }
  return <Field label={label} hint={hint}>{(id) => <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} />}</Field>;
}

function cleanSettings(s: ProviderSettings): ProviderSettings {
  const out: ProviderSettings = {};
  for (const [k, v] of Object.entries(s)) {
    if (Array.isArray(v)) out[k] = v.map((x) => x.trim()).filter(Boolean);
    else if (typeof v === 'number' && !Number.isFinite(v)) continue; // empty number → keep default
    else out[k] = v;
  }
  return out;
}

function ProviderForm({ kind, info }: { kind: ProviderKind; info: ProviderInfo }) {
  const [provider, setProvider] = useState(info.provider);
  const [settings, setSettings] = useState<ProviderSettings>(info.settings);
  const [apiKey, setApiKey] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const save = useAction((b: ProviderUpdate) => api.put(`/api/providers/${kind}`, b), {
    success: `${kind === 'stt' ? 'Speech-to-text' : 'Translation'} provider saved`,
    invalidate: [providersKey, keys.overview, keys.languages],
    onSuccess: () => {
      setApiKey('');
      setClearKey(false);
    },
  });

  const switching = provider !== info.provider;
  const needsKey = provider !== 'simulated';

  function changeProvider(p: string) {
    setProvider(p);
    setSettings(p === info.provider ? info.settings : { ...(info.options[p] ?? {}) });
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const body: ProviderUpdate = { provider, settings: cleanSettings(settings) };
    if (apiKey.trim()) body.api_key = apiKey.trim();
    else if (clearKey) body.clear_key = true;
    save.mutate(body);
  }

  return (
    <Card
      title={kind === 'stt' ? 'Speech-to-text provider' : 'Translation provider'}
      actions={
        !switching &&
        needsKey &&
        (info.has_key ? <Badge tone="green">Key saved ✓</Badge> : <Badge tone="red">No API key</Badge>)
      }
    >
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Provider" className="sm:col-span-2">
          {(id) => (
            <Select id={id} value={provider} onChange={(e) => changeProvider(e.target.value)}>
              {Object.keys(info.options).map((p) => (
                <option key={p} value={p}>
                  {PROVIDER_LABELS[p] ?? p}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {Object.entries(settings).map(([k, v]) => (
          <SettingInput key={`${provider}-${k}`} name={k} value={v} onChange={(nv) => setSettings((s) => ({ ...s, [k]: nv }))} />
        ))}
        {needsKey && (
          <div className="space-y-2 sm:col-span-2">
            <Field
              label="API key"
              hint={
                switching
                  ? 'Switching provider discards the stored key of the previous provider. Enter the key for the new provider.'
                  : info.has_key
                    ? 'Leave blank to keep the saved key. Keys are write-only and never shown again.'
                    : 'Keys are stored encrypted and never shown again.'
              }
            >
              {(id) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={info.has_key && !switching ? '•••••••• (saved)' : 'Paste API key'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              )}
            </Field>
            {info.has_key && !switching && !apiKey && <Checkbox checked={clearKey} onChange={setClearKey} label="Remove the saved key" />}
          </div>
        )}
        {provider === 'simulated' && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 sm:col-span-2">
            The simulated provider produces fake output. Use it only for testing.
          </div>
        )}
        <div className="flex justify-end sm:col-span-2">
          <Button type="submit" variant="primary" loading={save.isPending}>
            Save provider
          </Button>
        </div>
      </form>
    </Card>
  );
}

type NumKey = {
  [K in keyof GeneralSettings]-?: GeneralSettings[K] extends number ? K : never;
}[keyof GeneralSettings];

const NUMBER_FIELDS: { key: NumKey; label: string; hint: string; min: number; max: number }[] = [
  { key: 'manual_default_minutes', label: 'Default manual service length (min)', hint: 'Used by "Start service now".', min: 5, max: 720 },
  { key: 'ended_grace_minutes', label: 'Ended grace (min)', hint: 'How long the public page shows "service ended".', min: 0, max: 1440 },
  { key: 'lookahead_days', label: 'Schedule lookahead (days)', hint: 'How far ahead the next service is computed.', min: 1, max: 60 },
  { key: 'transcript_retention_days', label: 'Transcript retention (days)', hint: 'For campuses that retain transcripts.', min: 1, max: 3650 },
  { key: 'partial_min_interval_ms', label: 'Partial translation interval (ms)', hint: 'Minimum time between partial translations.', min: 500, max: 10000 },
  { key: 'language_grace_seconds', label: 'Language grace (s)', hint: 'Keep translating a language this long after its last viewer leaves.', min: 0, max: 3600 },
  { key: 'audio_timeout_seconds', label: 'Audio timeout (s)', hint: 'No audio for this long = "Audio disconnected".', min: 2, max: 60 },
  { key: 'digital_silence_seconds', label: 'Digital silence alert (s)', hint: 'Exact-zero audio for this long raises an error.', min: 5, max: 600 },
];

function GeneralSettingsForm({ initial }: { initial: GeneralSettings }) {
  const [form, setForm] = useState<GeneralSettings>(initial);
  const save = useAction((b: Partial<GeneralSettings>) => api.put<GeneralSettings>('/api/settings', b), {
    success: 'Settings saved',
    invalidate: [keys.settings, keys.qrLinks],
  });
  const set = <K extends keyof GeneralSettings>(k: K, v: GeneralSettings[K]) => setForm((f) => ({ ...f, [k]: v }));

  function submit(e: FormEvent) {
    e.preventDefault();
    const changes: Partial<GeneralSettings> = {};
    for (const k of Object.keys(form) as (keyof GeneralSettings)[]) {
      // Name and color are edited on the Branding page.
      if (k === 'effective_public_base_url' || k === 'church_name' || k === 'accent_color') continue;
      if (form[k] !== initial[k]) (changes as Record<string, unknown>)[k] = form[k];
    }
    if (Object.keys(changes).length === 0) return;
    save.mutate(changes);
  }

  return (
    <Card title="General settings">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Public base URL"
          hint={`Used for QR codes. Empty = server default${initial.effective_public_base_url ? ` (${initial.effective_public_base_url})` : ''}.`}
        >
          {(id) => (
            <Input id={id} type="url" maxLength={200} placeholder="https://captions.example.org" value={form.public_base_url} onChange={(e) => set('public_base_url', e.target.value)} />
          )}
        </Field>
        {NUMBER_FIELDS.map((f) => (
          <Field key={f.key} label={f.label} hint={f.hint}>
            {(id) => (
              <Input id={id} type="number" required min={f.min} max={f.max} value={form[f.key]} onChange={(e) => set(f.key, Number(e.target.value))} />
            )}
          </Field>
        ))}
        <div className="space-y-2 sm:col-span-2">
          <Toggle checked={form.translate_partials} onChange={(v) => set('translate_partials', v)} label="Translate partial (in-progress) captions" />
          {form.translate_partials && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <strong>Cost warning:</strong> partial captions are re-translated every {form.partial_min_interval_ms} ms per language while
              someone is speaking. This can multiply translation characters (and cost) several times over.
            </div>
          )}
        </div>
        <div className="flex justify-end sm:col-span-2">
          <Button type="submit" variant="primary" loading={save.isPending}>
            Save settings
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function ProvidersPage() {
  const q = useQuery({ queryKey: providersKey, queryFn: () => api.get<Providers>('/api/providers') });
  const settings = useSettings();
  return (
    <div className="space-y-5">
      <PageHeader title="Providers & settings" />
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <ErrorBox error={q.error} />
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* key = server state so forms reset after a save */}
          <ProviderForm key={JSON.stringify(q.data.stt)} kind="stt" info={q.data.stt} />
          <ProviderForm key={JSON.stringify(q.data.translation)} kind="translation" info={q.data.translation} />
        </div>
      )}
      {settings.isPending ? (
        <Loading />
      ) : settings.isError ? (
        <ErrorBox error={settings.error} />
      ) : (
        <GeneralSettingsForm key={JSON.stringify(settings.data)} initial={settings.data} />
      )}
    </div>
  );
}
