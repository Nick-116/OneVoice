import { useState, type FormEvent } from 'react';
import { api } from '../api';
import { useAuth } from '../auth/AuthContext';
import { LanguageSelect } from '../components/pickers';
import { Badge, Button, Card, Checkbox, ConfirmDialog, Empty, ErrorBox, Field, Input, Loading, PageHeader, Table, Td, Textarea, Th, Toggle } from '../components/ui';
import { keys, useAction, useLanguages } from '../lib/queries';
import type { Language, LanguageInput, TranslateTestResult } from '../types';

function SortOrderInput({ lang, disabled }: { lang: Language; disabled: boolean }) {
  const [v, setV] = useState(String(lang.sort_order));
  const save = useAction((n: number) => api.patch(`/api/languages/${lang.code}`, { sort_order: n }), { invalidate: [keys.languages] });
  const commit = () => {
    const n = Number(v);
    if (Number.isInteger(n) && n >= 0 && n <= 10000 && n !== lang.sort_order) save.mutate(n);
    else setV(String(lang.sort_order));
  };
  return (
    <Input
      type="number"
      min={0}
      max={10000}
      aria-label={`Sort order for ${lang.name_en}`}
      className="w-20 py-1"
      disabled={disabled}
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && commit()}
    />
  );
}

function AddLanguage() {
  const blank: LanguageInput = { code: '', name_en: '', native_name: '', rtl: false, enabled: true, sort_order: 500 };
  const [form, setForm] = useState<LanguageInput>(blank);
  const [providerCodes, setProviderCodes] = useState('');
  const set = <K extends keyof LanguageInput>(k: K, v: LanguageInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const add = useAction((body: LanguageInput & { provider_codes: Record<string, string> }) => api.post('/api/languages', body), {
    success: 'Language added',
    invalidate: [keys.languages],
    onSuccess: () => {
      setForm(blank);
      setProviderCodes('');
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const provider_codes: Record<string, string> = {};
    for (const line of providerCodes.split('\n')) {
      const [k, v] = line.split('=').map((s) => s.trim());
      if (k && v) provider_codes[k] = v;
    }
    add.mutate({ ...form, code: form.code.trim(), provider_codes });
  }

  return (
    <Card title="Add custom language">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Code" hint="BCP-47, e.g. ht or zh-Hant">
          {(id) => <Input id={id} required pattern="[a-z]{2,3}(-[A-Za-z0-9]{2,8})?" value={form.code} onChange={(e) => set('code', e.target.value)} />}
        </Field>
        <Field label="English name">{(id) => <Input id={id} required maxLength={80} value={form.name_en} onChange={(e) => set('name_en', e.target.value)} />}</Field>
        <Field label="Native name">{(id) => <Input id={id} required maxLength={80} value={form.native_name} onChange={(e) => set('native_name', e.target.value)} />}</Field>
        <Field label="Sort order">
          {(id) => <Input id={id} type="number" min={0} max={10000} value={form.sort_order} onChange={(e) => set('sort_order', Number(e.target.value))} />}
        </Field>
        <Field label="Provider code overrides (optional)" hint="One per line, e.g. azure=zh-Hant" className="sm:col-span-2">
          {(id) => <Textarea id={id} rows={2} value={providerCodes} onChange={(e) => setProviderCodes(e.target.value)} />}
        </Field>
        <div className="flex flex-col justify-end gap-2 sm:col-span-2 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex gap-4 pb-2">
            <Checkbox checked={form.rtl} onChange={(v) => set('rtl', v)} label="Right-to-left" />
            <Checkbox checked={form.enabled} onChange={(v) => set('enabled', v)} label="Enabled" />
          </div>
          <Button type="submit" variant="primary" loading={add.isPending}>
            Add language
          </Button>
        </div>
      </form>
    </Card>
  );
}

function TestTranslation({ languages }: { languages: Language[] }) {
  const targets = languages.filter((l) => l.code !== 'en');
  const [text, setText] = useState('Welcome! Please turn in your Bibles to John chapter three.');
  const [target, setTarget] = useState(targets.find((l) => l.code === 'es')?.code ?? targets[0]?.code ?? 'es');
  const [source, setSource] = useState('en');
  const test = useAction((b: { text: string; target: string; source: string }) => api.post<TranslateTestResult>('/api/languages/test', b));

  return (
    <Card title="Test translation">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          test.mutate({ text, target, source });
        }}
      >
        <Field label="Text" hint={`${text.length}/500`}>
          {(id) => <Textarea id={id} rows={3} maxLength={500} required value={text} onChange={(e) => setText(e.target.value)} />}
        </Field>
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Field label="From">{(id) => <LanguageSelect id={id} languages={languages} value={source} onChange={setSource} />}</Field>
          <Field label="To">{(id) => <LanguageSelect id={id} languages={targets} value={target} onChange={setTarget} />}</Field>
          <Button type="submit" variant="primary" loading={test.isPending}>
            Translate
          </Button>
        </div>
      </form>
      {test.data && (
        <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-3">
          <div className="mb-1 flex flex-wrap gap-2 text-xs text-gray-500">
            <Badge tone="indigo">{test.data.provider}</Badge>
            <span>{test.data.latency_ms} ms</span>
          </div>
          <p className="whitespace-pre-wrap text-sm text-gray-900" dir={languages.find((l) => l.code === target)?.rtl ? 'rtl' : 'auto'}>
            {test.data.text}
          </p>
        </div>
      )}
      {test.isError && (
        <div className="mt-3">
          <ErrorBox error={test.error} />
        </div>
      )}
    </Card>
  );
}

export function LanguagesPage() {
  const { isAdmin } = useAuth();
  const q = useLanguages();
  const [deleting, setDeleting] = useState<Language | null>(null);
  const toggle = useAction((l: Language) => api.patch(`/api/languages/${l.code}`, { enabled: !l.enabled }), {
    success: (_r, l) => `${l.name_en} ${l.enabled ? 'disabled' : 'enabled'}`,
    invalidate: [keys.languages],
  });
  const del = useAction((l: Language) => api.del(`/api/languages/${l.code}`), {
    success: 'Language deleted',
    invalidate: [keys.languages],
    onSuccess: () => setDeleting(null),
  });

  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;

  return (
    <div className="space-y-5">
      <PageHeader title="Languages" description="Enable the languages offered to viewers. Each campus chooses its own subset." />
      <Card>
        {q.data.length === 0 ? (
          <Empty>No languages.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Language</Th>
                <Th>Code</Th>
                <Th>Provider support</Th>
                <Th>Viewers now</Th>
                <Th>Sort</Th>
                <Th>Enabled</Th>
                {isAdmin && <Th />}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {q.data.map((l) => (
                <tr key={l.code}>
                  <Td>
                    <div className="font-medium" dir={l.rtl ? 'rtl' : 'ltr'}>
                      {l.native_name}
                    </div>
                    <div className="text-xs text-gray-500">
                      {l.name_en}
                      {l.rtl && ' · RTL'}
                      {!l.builtin && ' · custom'}
                    </div>
                  </Td>
                  <Td className="font-mono text-xs">{l.code}</Td>
                  <Td>{l.provider_supported ? <Badge tone="green">supported</Badge> : <Badge tone="amber">not supported</Badge>}</Td>
                  <Td className="tabular-nums">{l.viewers}</Td>
                  <Td>
                    <SortOrderInput key={l.sort_order} lang={l} disabled={!isAdmin} />
                  </Td>
                  <Td>
                    <Toggle checked={l.enabled} disabled={!isAdmin || toggle.isPending} onChange={() => toggle.mutate(l)} srLabel={`Enable ${l.name_en}`} />
                  </Td>
                  {isAdmin && (
                    <Td className="text-right">
                      {!l.builtin && (
                        <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setDeleting(l)}>
                          Delete
                        </Button>
                      )}
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <div className="grid gap-5 lg:grid-cols-2">
        <TestTranslation languages={q.data} />
        {isAdmin && <AddLanguage />}
      </div>
      <ConfirmDialog
        open={!!deleting}
        title={`Delete ${deleting?.name_en}?`}
        message="The custom language is removed from every campus."
        confirmLabel="Delete"
        busy={del.isPending}
        onConfirm={() => deleting && del.mutate(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
