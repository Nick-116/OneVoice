import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { api } from '../api';
import { useAuth } from '../auth/AuthContext';
import { LevelMeter } from '../components/LevelMeter';
import { CampusSelect } from '../components/pickers';
import { useToast } from '../components/Toast';
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  CopyButton,
  Empty,
  ErrorBox,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  StatusDot,
  Table,
  Td,
  Textarea,
  Th,
} from '../components/ui';
import { useAction, useCampuses, useNow } from '../lib/queries';
import { formatDuration, formatInZone, relativeTime } from '../lib/time';
import type { AudioCampus, Campus, Sender, SenderCreated } from '../types';

const audioKey = ['audio'] as const;
const sendersKey = ['senders'] as const;

function AudioCard({ item, now }: { item: AudioCampus; now: number }) {
  const { campus, audio, history } = item;
  const tz = campus.timezone;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <StatusDot tone={audio.connected ? 'green' : 'red'} pulse={audio.connected} />
          {campus.name}
        </span>
      }
      actions={
        <>
          <Badge tone={campus.audio_source === 'local' ? 'blue' : 'gray'}>{campus.audio_source === 'local' ? 'Local input' : 'Sender app'}</Badge>
          {audio.connected ? <Badge tone="green">Connected</Badge> : <Badge tone="red">Disconnected</Badge>}
          {audio.connected && (audio.forwarding ? <Badge tone="green">Forwarding to STT</Badge> : <Badge tone="gray">Meter only (no service)</Badge>)}
        </>
      }
    >
      {audio.local_error && <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{audio.local_error}</p>}
      <LevelMeter level={audio.level_dbfs} peak={audio.peak_dbfs} active={audio.connected} />
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-gray-500">Source</dt>
          <dd>{audio.sender_name ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">Remote IP</dt>
          <dd className="font-mono text-xs">{audio.remote_ip ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">Last audio received</dt>
          <dd>{relativeTime(audio.last_frame_at, now)}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">Last signal (non-silence)</dt>
          <dd>{relativeTime(audio.last_signal_at, now)}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">Format</dt>
          <dd>
            {audio.format ?? '—'}
            {audio.sample_rate ? ` · ${(audio.sample_rate / 1000).toFixed(1)} kHz` : ''}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">{audio.connected ? 'Connected for' : 'Disconnected'}</dt>
          <dd>
            {audio.connected && audio.connected_at
              ? formatDuration(now - audio.connected_at * 1000)
              : audio.disconnected_at
                ? relativeTime(audio.disconnected_at, now)
                : '—'}
          </dd>
        </div>
      </dl>
      <div className="mt-4">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Connection history</h3>
        {history.length === 0 ? (
          <p className="text-sm text-gray-500">No connections recorded.</p>
        ) : (
          <ol className="relative max-h-56 space-y-2 overflow-y-auto border-l border-gray-200 pl-4">
            {history.map((h, i) => (
              <li key={`${h.at}-${i}`} className="relative text-sm">
                <span
                  className={
                    'absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-white ' +
                    (h.event === 'connected' ? 'bg-green-500' : 'bg-red-500')
                  }
                  aria-hidden="true"
                />
                <span className="font-medium">{h.event === 'connected' ? 'Connected' : h.event === 'disconnected' ? 'Disconnected' : h.event}</span>
                <span className="ml-2 text-xs text-gray-500">{formatInZone(h.at, tz, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' })}</span>
                <div className="text-xs text-gray-600">
                  {[h.sender, h.ip, h.reason, h.duration != null ? `lasted ${formatDuration(h.duration * 1000)}` : null].filter(Boolean).join(' · ')}
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </Card>
  );
}

function parseCidrs(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function SenderModal({ campuses, initial, onClose, onCreated }: { campuses: Campus[]; initial: Sender | null; onClose: () => void; onCreated: (s: SenderCreated) => void }) {
  const [campusId, setCampusId] = useState<number>(initial?.campus_id ?? campuses[0]?.id ?? 0);
  const [name, setName] = useState(initial?.name ?? '');
  const [cidrs, setCidrs] = useState(initial?.allowed_cidrs.join('\n') ?? '');
  const save = useAction(
    (b: { campus_id: number; name: string; allowed_cidrs: string[] }) =>
      initial
        ? api.patch<Sender>(`/api/senders/${initial.id}`, { name: b.name, allowed_cidrs: b.allowed_cidrs })
        : api.post<SenderCreated>('/api/senders', b),
    {
      success: initial ? 'Sender updated' : undefined,
      invalidate: [sendersKey],
      onSuccess: (r) => {
        if (!initial) onCreated(r as SenderCreated);
        onClose();
      },
    },
  );
  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate({ campus_id: campusId, name: name.trim(), allowed_cidrs: parseCidrs(cidrs) });
  }
  return (
    <Modal
      open
      onClose={onClose}
      title={initial ? 'Edit audio sender' : 'New audio sender'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="sender-form" loading={save.isPending}>
            {initial ? 'Save' : 'Create & show token'}
          </Button>
        </>
      }
    >
      <form id="sender-form" onSubmit={submit} className="space-y-4">
        {!initial && (
          <Field label="Campus">{(id) => <CampusSelect id={id} campuses={campuses} value={campusId} onChange={setCampusId} />}</Field>
        )}
        <Field label="Name" hint="e.g. Main campus sound booth">
          {(id) => <Input id={id} required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Allowed source networks (optional)" hint="CIDRs, one per line (e.g. 203.0.113.10/32). Empty = any address.">
          {(id) => <Textarea id={id} rows={3} className="font-mono" value={cidrs} onChange={(e) => setCidrs(e.target.value)} />}
        </Field>
      </form>
    </Modal>
  );
}

function TokenModal({ sender, onClose }: { sender: SenderCreated | null; onClose: () => void }) {
  const toast = useToast();
  return (
    <Modal
      open={!!sender}
      onClose={onClose}
      dismissable={false}
      title="Sender token — copy it now"
      footer={
        <Button variant="primary" onClick={onClose}>
          I have saved the token
        </Button>
      }
    >
      {sender && (
        <div className="space-y-3">
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
            This token is shown <strong>only once</strong>. Store it in the sender's configuration now. Anyone with it can feed
            audio into <strong>{sender.name}</strong>'s campus. If it is lost, revoke this sender and create a new one.
          </div>
          <div className="flex items-start gap-2 rounded-md bg-gray-900 p-3">
            <code className="flex-1 select-all break-all font-mono text-xs text-green-300">{sender.token}</code>
            <CopyButton text={sender.token} onCopied={() => toast.success('Token copied')} />
          </div>
        </div>
      )}
    </Modal>
  );
}

function SendersSection({ campuses }: { campuses: Campus[] }) {
  const q = useQuery({ queryKey: sendersKey, queryFn: () => api.get<Sender[]>('/api/senders') });
  const [editing, setEditing] = useState<Sender | 'new' | null>(null);
  const [created, setCreated] = useState<SenderCreated | null>(null);
  const [confirm, setConfirm] = useState<{ sender: Sender; action: 'revoke' | 'delete' } | null>(null);
  const revoke = useAction((s: Sender) => api.post(`/api/senders/${s.id}/revoke`), {
    success: 'Sender revoked — it is disconnected now',
    invalidate: [sendersKey],
    onSuccess: () => setConfirm(null),
  });
  const del = useAction((s: Sender) => api.del(`/api/senders/${s.id}`), {
    success: 'Sender deleted',
    invalidate: [sendersKey],
    onSuccess: () => setConfirm(null),
  });
  const campusName = (id: number) => campuses.find((c) => c.id === id)?.name ?? `#${id}`;

  return (
    <Card
      title="Audio senders"
      actions={
        <Button variant="primary" size="sm" onClick={() => setEditing('new')} disabled={!campuses.length}>
          + New sender
        </Button>
      }
    >
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <ErrorBox error={q.error} />
      ) : q.data.length === 0 ? (
        <Empty>No audio senders. Create one to get a token for the booth sender.</Empty>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Name</Th>
              <Th>Campus</Th>
              <Th>Allowed networks</Th>
              <Th>Created</Th>
              <Th>Status</Th>
              <Th />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {q.data.map((s) => (
              <tr key={s.id} className={s.revoked_at ? 'opacity-60' : undefined}>
                <Td className="font-medium">{s.name}</Td>
                <Td>{campusName(s.campus_id)}</Td>
                <Td className="font-mono text-xs">{s.allowed_cidrs.length ? s.allowed_cidrs.join(', ') : <span className="font-sans text-gray-500">any</span>}</Td>
                <Td className="text-xs">{formatInZone(s.created_at)}</Td>
                <Td>{s.revoked_at ? <Badge tone="red">Revoked</Badge> : <Badge tone="green">Active</Badge>}</Td>
                <Td className="whitespace-nowrap text-right">
                  {!s.revoked_at && (
                    <>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(s)}>
                        Edit
                      </Button>
                      <Button size="sm" variant="ghost" className="text-amber-700" onClick={() => setConfirm({ sender: s, action: 'revoke' })}>
                        Revoke
                      </Button>
                    </>
                  )}
                  <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setConfirm({ sender: s, action: 'delete' })}>
                    Delete
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {editing && (
        <SenderModal campuses={campuses} initial={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onCreated={setCreated} />
      )}
      <TokenModal sender={created} onClose={() => setCreated(null)} />
      <ConfirmDialog
        open={!!confirm}
        title={confirm?.action === 'revoke' ? `Revoke ${confirm.sender.name}?` : `Delete ${confirm?.sender.name}?`}
        message={
          confirm?.action === 'revoke'
            ? 'The token stops working immediately and any live connection is dropped. If a service is running, captions stop until a new sender connects.'
            : 'The sender and its token are permanently removed; any live connection is dropped.'
        }
        confirmLabel={confirm?.action === 'revoke' ? 'Revoke' : 'Delete'}
        busy={revoke.isPending || del.isPending}
        onConfirm={() => confirm && (confirm.action === 'revoke' ? revoke.mutate(confirm.sender) : del.mutate(confirm.sender))}
        onCancel={() => setConfirm(null)}
      />
    </Card>
  );
}

export function AudioPage() {
  const { isAdmin } = useAuth();
  const q = useQuery({ queryKey: audioKey, queryFn: () => api.get<AudioCampus[]>('/api/audio'), refetchInterval: 3000 });
  const campuses = useCampuses();
  const now = useNow(1000);

  return (
    <div className="space-y-5">
      <PageHeader title="Audio" description="Booth audio senders for each campus · refreshes every 3 s" />
      {q.isPending ? (
        <Loading />
      ) : q.isError && !q.data ? (
        <ErrorBox error={q.error} />
      ) : q.data!.length === 0 ? (
        <Empty>No campuses.</Empty>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {q.data!.map((item) => (
            <AudioCard key={item.campus.id} item={item} now={now} />
          ))}
        </div>
      )}
      {isAdmin && campuses.data && <SendersSection campuses={campuses.data} />}
    </div>
  );
}
