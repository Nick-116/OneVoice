import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { api } from '../api';
import { LanguageChecklist, LanguageSelect, TimezoneSelect } from '../components/pickers';
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Empty,
  ErrorBox,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  Select,
  Table,
  Td,
  Th,
  Toggle,
} from '../components/ui';
import { keys, useAction, useCampuses, useLanguages, useSettings } from '../lib/queries';
import { formatInZone } from '../lib/time';
import type { Campus, CampusInput, Language, LocalAudioState, TranscriptEntry } from '../types';

const BLANK: CampusInput = {
  slug: '',
  name: '',
  timezone: 'America/New_York',
  source_language: 'en',
  default_language: 'en',
  enabled: true,
  retain_transcripts: false,
  languages: ['en', 'es'],
  audio_source: 'local',
  local_device: null,
  local_channel: 1,
};

function AudioSourceFields({ form, set }: { form: CampusInput; set: <K extends keyof CampusInput>(k: K, v: CampusInput[K]) => void }) {
  const local = useQuery({ queryKey: ['audio-local'], queryFn: () => api.get<LocalAudioState>('/api/audio/local'), refetchInterval: 5000 });
  const devices = local.data?.devices ?? [];
  const device = devices.find((d) => d.name === form.local_device);
  const channels = device?.channels ?? Math.max(form.local_channel, 1);
  return (
    <div className="space-y-3 rounded-md border border-gray-200 p-3 sm:col-span-2">
      <div className="text-sm font-medium text-gray-700">Audio source</div>
      <div className="grid gap-2 sm:grid-cols-2">
        {(
          [
            ['local', 'Local input on this server', 'An audio interface plugged into the OneVoice server (default).'],
            ['remote', 'Remote sender app', 'The OneVoice Sender app on a computer at church streams the audio.'],
          ] as const
        ).map(([value, title, desc]) => (
          <label
            key={value}
            className={`flex cursor-pointer gap-2 rounded-md border p-2 text-sm ${form.audio_source === value ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200'}`}
          >
            <input type="radio" name="audio_source" className="mt-1" checked={form.audio_source === value} onChange={() => set('audio_source', value)} />
            <span>
              <span className="block font-medium text-gray-900">{title}</span>
              <span className="block text-xs text-gray-500">{desc}</span>
            </span>
          </label>
        ))}
      </div>
      {form.audio_source === 'local' ? (
        <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
          <Field
            label="Input device"
            hint={
              local.data && !local.data.online
                ? 'The local-audio service is not running on this server. Enable it with COMPOSE_PROFILES=local-audio (Linux host with an audio interface), or choose Remote sender app.'
                : 'Devices found on the server. Dante Virtual Soundcard or a USB interface appears here.'
            }
          >
            {(id) => (
              <Select id={id} value={form.local_device ?? ''} onChange={(e) => set('local_device', e.target.value || null)}>
                <option value="">Select a device…</option>
                {form.local_device && !device && <option value={form.local_device}>{form.local_device} (not connected)</option>}
                {devices.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.name} · {d.channels} ch
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Channel" hint="Where the speech mix arrives.">
            {(id) => (
              <Select id={id} value={String(form.local_channel)} onChange={(e) => set('local_channel', Number(e.target.value))}>
                {Array.from({ length: channels }, (_, i) => (
                  <option key={i + 1} value={i + 1}>
                    Channel {i + 1}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
      ) : (
        <p className="text-xs text-gray-600">
          After saving, create a sender token under <strong>Audio → Senders</strong> and paste it into the OneVoice Sender app.
        </p>
      )}
    </div>
  );
}

function CampusModal({ initial, languages, onClose }: { initial: Campus | null; languages: Language[]; onClose: () => void }) {
  const settings = useSettings();
  const [form, setForm] = useState<CampusInput>(() => {
    if (!initial) return BLANK;
    const { id: _id, ...rest } = initial;
    return rest;
  });
  const set = <K extends keyof CampusInput>(k: K, v: CampusInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const save = useAction(
    (body: CampusInput) => (initial ? api.patch<Campus>(`/api/campuses/${initial.id}`, body) : api.post<Campus>('/api/campuses', body)),
    { success: initial ? 'Campus updated' : 'Campus created', invalidate: [keys.campuses, keys.overview, keys.qrLinks], onSuccess: onClose },
  );
  const langs = Array.from(new Set([form.source_language, ...form.languages]));
  const base = settings.data?.effective_public_base_url ?? '';

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate({ ...form, slug: form.slug.trim().toLowerCase(), languages: langs });
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={initial ? `Edit ${initial.name}` : 'New campus'}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="campus-form" loading={save.isPending}>
            Save
          </Button>
        </>
      }
    >
      <form id="campus-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Name">{(id) => <Input id={id} required maxLength={120} value={form.name} onChange={(e) => set('name', e.target.value)} />}</Field>
        <Field label="Slug" hint={base ? `Public page: ${base}/${form.slug || 'slug'}` : 'Lowercase letters, digits and dashes.'}>
          {(id) => (
            <Input
              id={id}
              required
              maxLength={64}
              value={form.slug}
              onChange={(e) => set('slug', e.target.value.toLowerCase())}
            />
          )}
        </Field>
        <Field label="Time zone">{(id) => <TimezoneSelect id={id} value={form.timezone} onChange={(v) => set('timezone', v)} />}</Field>
        <Field label="Source (spoken) language">
          {(id) => <LanguageSelect id={id} languages={languages} value={form.source_language} onChange={(v) => set('source_language', v)} />}
        </Field>
        <Field label="Default viewer language">
          {(id) => <LanguageSelect id={id} languages={languages} only={langs} value={form.default_language} onChange={(v) => set('default_language', v)} />}
        </Field>
        <div className="flex items-end pb-2">
          <Toggle checked={form.enabled} onChange={(v) => set('enabled', v)} label="Campus enabled" />
        </div>
        <div className="sm:col-span-2">
          <div className="mb-1 text-sm font-medium text-gray-700">Enabled languages</div>
          <LanguageChecklist languages={languages} value={form.languages} onChange={(v) => set('languages', v)} locked={[form.source_language]} />
        </div>
        <AudioSourceFields form={form} set={set} />
        <div className="space-y-2 sm:col-span-2">
          <Toggle checked={form.retain_transcripts} onChange={(v) => set('retain_transcripts', v)} label="Retain transcripts" />
          {form.retain_transcripts && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <strong>Privacy:</strong> everything said during services (including prayer requests, names and pastoral
              content) will be stored as text for {settings.data?.transcript_retention_days ?? 'the configured number of'} days.
              Make sure your church's privacy policy covers this and that speakers are aware.
            </div>
          )}
        </div>
      </form>
    </Modal>
  );
}

function Transcripts({ campus }: { campus: Campus }) {
  const q = useQuery({
    queryKey: ['transcripts', campus.id],
    queryFn: () => api.get<TranscriptEntry[]>(`/api/campuses/${campus.id}/transcripts`),
  });
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  if (!q.data.length) return <Empty>No transcripts stored for {campus.name}.</Empty>;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Started</Th>
          <Th>Occurrence</Th>
          <Th>Language</Th>
          <Th>Segments</Th>
          <Th />
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {q.data.map((t) => {
          const href = `/api/campuses/${campus.id}/transcripts/download?occurrence=${encodeURIComponent(t.occurrence)}&language=${encodeURIComponent(t.language)}`;
          return (
            <tr key={`${t.occurrence}-${t.language}`}>
              <Td>{formatInZone(t.started, campus.timezone)}</Td>
              <Td className="font-mono text-xs">{t.occurrence}</Td>
              <Td>{t.language}</Td>
              <Td className="tabular-nums">{t.segments}</Td>
              <Td className="text-right">
                <a href={href} download={`${t.occurrence}-${t.language}.txt`} className="text-sm font-medium text-indigo-600 hover:underline">
                  Download
                </a>
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

export function CampusesPage() {
  const campuses = useCampuses();
  const languages = useLanguages();
  const [editing, setEditing] = useState<Campus | 'new' | null>(null);
  const [deleting, setDeleting] = useState<Campus | null>(null);
  const [transcripts, setTranscripts] = useState<number | null>(null);
  const del = useAction((c: Campus) => api.del(`/api/campuses/${c.id}`), {
    success: 'Campus deleted',
    invalidate: [keys.campuses, keys.overview, keys.qrLinks],
    onSuccess: () => setDeleting(null),
  });

  if (campuses.isPending || languages.isPending) return <Loading />;
  if (campuses.isError) return <ErrorBox error={campuses.error} />;
  if (languages.isError) return <ErrorBox error={languages.error} />;
  const langName = (c: string) => languages.data.find((l) => l.code === c)?.name_en ?? c;
  const selected = campuses.data.find((c) => c.id === transcripts) ?? null;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Campuses"
        actions={
          <Button variant="primary" onClick={() => setEditing('new')}>
            + New campus
          </Button>
        }
      />
      <Card>
        {campuses.data.length === 0 ? (
          <Empty>No campuses yet.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Campus</Th>
                <Th>Time zone</Th>
                <Th>Source / default</Th>
                <Th>Languages</Th>
                <Th>Status</Th>
                <Th />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {campuses.data.map((c) => (
                <tr key={c.id}>
                  <Td>
                    <div className="font-medium">{c.name}</div>
                    <div className="font-mono text-xs text-gray-500">/{c.slug}</div>
                  </Td>
                  <Td className="text-xs">{c.timezone}</Td>
                  <Td className="text-xs">
                    {langName(c.source_language)} / {langName(c.default_language)}
                  </Td>
                  <Td className="max-w-xs text-xs">{c.languages.map(langName).join(', ')}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {c.enabled ? <Badge tone="green">Enabled</Badge> : <Badge tone="gray">Disabled</Badge>}
                      {c.retain_transcripts && <Badge tone="amber">Transcripts kept</Badge>}
                      <Badge tone={c.audio_source === 'local' ? 'blue' : 'gray'}>
                        {c.audio_source === 'local' ? `Local input${c.local_device ? `: ${c.local_device}` : ''}` : 'Sender app'}
                      </Badge>
                    </div>
                  </Td>
                  <Td className="whitespace-nowrap text-right">
                    {c.retain_transcripts && (
                      <Button size="sm" variant="ghost" onClick={() => setTranscripts(c.id === transcripts ? null : c.id)}>
                        Transcripts
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => setEditing(c)}>
                      Edit
                    </Button>
                    <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setDeleting(c)}>
                      Delete
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {selected && (
        <Card title={`Transcripts — ${selected.name}`} actions={<Button size="sm" onClick={() => setTranscripts(null)}>Close</Button>}>
          <Transcripts campus={selected} />
        </Card>
      )}

      {editing && <CampusModal initial={editing === 'new' ? null : editing} languages={languages.data} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={!!deleting}
        title={`Delete ${deleting?.name}?`}
        message="This permanently removes the campus with its schedules, events, audio senders and stored transcripts. The public page and QR code stop working."
        confirmLabel="Delete campus"
        busy={del.isPending}
        onConfirm={() => deleting && del.mutate(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
