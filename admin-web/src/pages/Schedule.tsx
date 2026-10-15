import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { api } from '../api';
import { useAuth } from '../auth/AuthContext';
import { CampusSelect, LanguageChecklist, TimezoneSelect } from '../components/pickers';
import { KindBadge } from '../components/status';
import {
  Badge,
  Button,
  Card,
  Checkbox,
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
import { useAction, useCampuses, useLanguages } from '../lib/queries';
import { formatInZone, formatTime, isoToZonedLocal, to12h, WEEKDAYS, zonedLocalToIso, zoneAbbr } from '../lib/time';
import { useSelectedCampus } from '../lib/useSelectedCampus';
import type { Campus, Language, Occurrence, Schedule, ScheduleInput, ServiceEvent } from '../types';

const schedKey = (cid: number) => ['schedules', cid] as const;
const eventKey = (cid: number) => ['events', cid] as const;
const occKey = (cid: number) => ['occurrences', cid] as const;

// ---------------------------------------------------------------- language subset (null = all campus languages)
function LanguageSubset({
  campus,
  languages,
  value,
  onChange,
}: {
  campus: Campus;
  languages: Language[];
  value: string[] | null;
  onChange: (v: string[] | null) => void;
}) {
  const campusLangs = languages.filter((l) => campus.languages.includes(l.code));
  return (
    <div className="space-y-2">
      <Checkbox checked={value === null} onChange={(all) => onChange(all ? null : [...campus.languages])} label="All campus languages" />
      {value !== null && <LanguageChecklist languages={campusLangs} value={value} onChange={onChange} locked={[campus.source_language]} />}
    </div>
  );
}

// ---------------------------------------------------------------- recurring schedule modal
function emptySchedule(campus: Campus): ScheduleInput {
  return {
    campus_id: campus.id,
    name: 'Sunday service',
    weekday: 6,
    start_time: '09:00',
    end_time: '10:30',
    timezone: campus.timezone || 'America/New_York',
    enabled: true,
    early_access_minutes: 15,
    languages: null,
    valid_from: null,
    valid_until: null,
  };
}

function ScheduleModal({
  campus,
  languages,
  initial,
  onClose,
}: {
  campus: Campus;
  languages: Language[];
  initial: Schedule | null;
  onClose: () => void;
}) {
  // The backend rejects unknown fields (extra="forbid"), so strip `id` from the edited row.
  const [form, setForm] = useState<ScheduleInput>(() => {
    if (!initial) return emptySchedule(campus);
    const { id: _id, ...rest } = initial;
    return rest;
  });
  const set = <K extends keyof ScheduleInput>(k: K, v: ScheduleInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const save = useAction(
    (body: ScheduleInput) => (initial ? api.patch(`/api/schedules/${initial.id}`, body) : api.post('/api/schedules', body)),
    { success: initial ? 'Schedule updated' : 'Schedule created', invalidate: [schedKey(campus.id), occKey(campus.id)], onSuccess: onClose },
  );

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate({ ...form, valid_from: form.valid_from || null, valid_until: form.valid_until || null });
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={initial ? 'Edit recurring service' : 'New recurring service'}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="sched-form" loading={save.isPending}>
            Save
          </Button>
        </>
      }
    >
      <form id="sched-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" className="sm:col-span-2">
          {(id) => <Input id={id} required maxLength={120} value={form.name} onChange={(e) => set('name', e.target.value)} />}
        </Field>
        <Field label="Day of week">
          {(id) => (
            <Select id={id} value={form.weekday} onChange={(e) => set('weekday', Number(e.target.value))}>
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Time zone">{(id) => <TimezoneSelect id={id} value={form.timezone} onChange={(v) => set('timezone', v)} />}</Field>
        <Field label="Start time" hint={to12h(form.start_time)}>
          {(id) => <Input id={id} type="time" required value={form.start_time} onChange={(e) => set('start_time', e.target.value)} />}
        </Field>
        <Field label="End time" hint={`${to12h(form.end_time)}${form.end_time < form.start_time ? ' (next day)' : ''}`}>
          {(id) => <Input id={id} type="time" required value={form.end_time} onChange={(e) => set('end_time', e.target.value)} />}
        </Field>
        <Field label="Early access (minutes)" hint="Viewers can open the page and captions start this long before the service.">
          {(id) => (
            <Input id={id} type="number" min={0} max={240} value={form.early_access_minutes} onChange={(e) => set('early_access_minutes', Number(e.target.value))} />
          )}
        </Field>
        <div className="flex items-end pb-2">
          <Toggle checked={form.enabled} onChange={(v) => set('enabled', v)} label="Enabled" />
        </div>
        <Field label="Valid from (optional)">
          {(id) => <Input id={id} type="date" value={form.valid_from ?? ''} onChange={(e) => set('valid_from', e.target.value || null)} />}
        </Field>
        <Field label="Valid until (optional)">
          {(id) => <Input id={id} type="date" value={form.valid_until ?? ''} onChange={(e) => set('valid_until', e.target.value || null)} />}
        </Field>
        <div className="sm:col-span-2">
          <div className="mb-1 text-sm font-medium text-gray-700">Languages</div>
          <LanguageSubset campus={campus} languages={languages} value={form.languages} onChange={(v) => set('languages', v)} />
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------- one-time event modal
interface EventForm {
  name: string;
  kind: 'special' | 'holiday';
  start: string; // datetime-local in tz
  end: string;
  timezone: string;
  early_access_minutes: number;
  languages: string[] | null;
}

function EventModal({
  campus,
  languages,
  initial,
  onClose,
}: {
  campus: Campus;
  languages: Language[];
  initial: ServiceEvent | null;
  onClose: () => void;
}) {
  const tz0 = campus.timezone || 'America/New_York';
  const [form, setForm] = useState<EventForm>(() =>
    initial
      ? {
          name: initial.name,
          kind: initial.kind === 'holiday' ? 'holiday' : 'special',
          start: isoToZonedLocal(initial.start_at, tz0),
          end: isoToZonedLocal(initial.end_at, tz0),
          timezone: tz0,
          early_access_minutes: initial.early_access_minutes,
          languages: initial.languages,
        }
      : { name: '', kind: 'special', start: '', end: '', timezone: tz0, early_access_minutes: 15, languages: null },
  );
  const [localError, setLocalError] = useState('');
  const set = <K extends keyof EventForm>(k: K, v: EventForm[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = useAction(
    (body: Record<string, unknown>) => (initial ? api.patch(`/api/events/${initial.id}`, body) : api.post('/api/events', body)),
    { success: initial ? 'Event updated' : 'Event created', invalidate: [eventKey(campus.id), occKey(campus.id)], onSuccess: onClose },
  );

  let preview = '';
  try {
    if (form.start) preview = zonedLocalToIso(form.start, form.timezone);
  } catch {
    preview = '';
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    let start_at: string;
    let end_at: string;
    try {
      start_at = zonedLocalToIso(form.start, form.timezone);
      end_at = zonedLocalToIso(form.end, form.timezone);
    } catch {
      return setLocalError('Enter a valid start and end date/time.');
    }
    if (Date.parse(end_at) <= Date.parse(start_at)) return setLocalError('End must be after start.');
    setLocalError('');
    const body: Record<string, unknown> = {
      name: form.name,
      kind: form.kind,
      start_at,
      end_at,
      early_access_minutes: form.early_access_minutes,
      languages: form.languages,
    };
    if (!initial) body.campus_id = campus.id;
    save.mutate(body);
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={initial ? 'Edit special event' : 'New special / holiday event'}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="event-form" loading={save.isPending}>
            Save
          </Button>
        </>
      }
    >
      <form id="event-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" className="sm:col-span-2">
          {(id) => <Input id={id} required maxLength={120} placeholder="Christmas Eve" value={form.name} onChange={(e) => set('name', e.target.value)} />}
        </Field>
        <Field label="Kind">
          {(id) => (
            <Select id={id} value={form.kind} onChange={(e) => set('kind', e.target.value as EventForm['kind'])}>
              <option value="special">Special</option>
              <option value="holiday">Holiday</option>
            </Select>
          )}
        </Field>
        <Field label="Time zone">{(id) => <TimezoneSelect id={id} value={form.timezone} onChange={(v) => set('timezone', v)} />}</Field>
        <Field label="Starts" hint={preview ? `Sent as ${preview}` : undefined}>
          {(id) => <Input id={id} type="datetime-local" required value={form.start} onChange={(e) => set('start', e.target.value)} />}
        </Field>
        <Field label="Ends" hint="Maximum 24 hours.">
          {(id) => <Input id={id} type="datetime-local" required value={form.end} onChange={(e) => set('end', e.target.value)} />}
        </Field>
        <Field label="Early access (minutes)">
          {(id) => (
            <Input id={id} type="number" min={0} max={240} value={form.early_access_minutes} onChange={(e) => set('early_access_minutes', Number(e.target.value))} />
          )}
        </Field>
        <div className="sm:col-span-2">
          <div className="mb-1 text-sm font-medium text-gray-700">Languages</div>
          <LanguageSubset campus={campus} languages={languages} value={form.languages} onChange={(v) => set('languages', v)} />
        </div>
        {localError && (
          <div className="sm:col-span-2">
            <ErrorBox error={localError} />
          </div>
        )}
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------- sections
function SchedulesSection({ campus, languages }: { campus: Campus; languages: Language[] }) {
  const { isAdmin } = useAuth();
  const q = useQuery({ queryKey: schedKey(campus.id), queryFn: () => api.get<Schedule[]>(`/api/schedules?campus_id=${campus.id}`) });
  const [editing, setEditing] = useState<Schedule | 'new' | null>(null);
  const [deleting, setDeleting] = useState<Schedule | null>(null);
  const invalidate = [schedKey(campus.id), occKey(campus.id)];
  const toggle = useAction((s: Schedule) => api.patch(`/api/schedules/${s.id}`, { enabled: !s.enabled }), { invalidate });
  const del = useAction((s: Schedule) => api.del(`/api/schedules/${s.id}`), {
    success: 'Schedule deleted',
    invalidate,
    onSuccess: () => setDeleting(null),
  });

  return (
    <Card
      title="Recurring services"
      actions={
        isAdmin && (
          <Button variant="primary" size="sm" onClick={() => setEditing('new')}>
            + Add recurring service
          </Button>
        )
      }
    >
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <ErrorBox error={q.error} />
      ) : q.data.length === 0 ? (
        <Empty>No recurring services for this campus.</Empty>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Name</Th>
              <Th>Day</Th>
              <Th>Time</Th>
              <Th>Zone</Th>
              <Th>Early access</Th>
              <Th>Languages</Th>
              <Th>Enabled</Th>
              {isAdmin && <Th />}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {q.data.map((s) => (
              <tr key={s.id}>
                <Td className="font-medium">
                  {s.name}
                  {(s.valid_from || s.valid_until) && (
                    <div className="text-xs font-normal text-gray-500">
                      {s.valid_from ?? '…'} → {s.valid_until ?? '…'}
                    </div>
                  )}
                </Td>
                <Td>{WEEKDAYS[s.weekday]}</Td>
                <Td className="whitespace-nowrap">
                  {to12h(s.start_time)} – {to12h(s.end_time)}
                </Td>
                <Td className="text-xs text-gray-600">{s.timezone}</Td>
                <Td>{s.early_access_minutes} min</Td>
                <Td className="text-xs">{s.languages ? s.languages.join(', ') : <span className="text-gray-500">all</span>}</Td>
                <Td>
                  <Toggle checked={s.enabled} disabled={!isAdmin || toggle.isPending} onChange={() => toggle.mutate(s)} srLabel={`Enable ${s.name}`} />
                </Td>
                {isAdmin && (
                  <Td className="whitespace-nowrap text-right">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(s)}>
                      Edit
                    </Button>
                    <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setDeleting(s)}>
                      Delete
                    </Button>
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {editing && (
        <ScheduleModal campus={campus} languages={languages} initial={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />
      )}
      <ConfirmDialog
        open={!!deleting}
        title="Delete recurring service?"
        message={`"${deleting?.name}" and all its exceptions will be removed. Future occurrences will no longer be captioned.`}
        confirmLabel="Delete"
        busy={del.isPending}
        onConfirm={() => deleting && del.mutate(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </Card>
  );
}

function EventsSection({ campus, languages }: { campus: Campus; languages: Language[] }) {
  const { isAdmin } = useAuth();
  const [includePast, setIncludePast] = useState(false);
  const q = useQuery({
    queryKey: [...eventKey(campus.id), includePast],
    queryFn: () => api.get<ServiceEvent[]>(`/api/events?campus_id=${campus.id}&include_past=${includePast}`),
  });
  const [editing, setEditing] = useState<ServiceEvent | 'new' | null>(null);
  const [deleting, setDeleting] = useState<ServiceEvent | null>(null);
  const invalidate = [eventKey(campus.id), occKey(campus.id)];
  const cancel = useAction((ev: ServiceEvent) => api.patch(`/api/events/${ev.id}`, { cancelled: !ev.cancelled }), {
    success: (_r, ev) => (ev.cancelled ? 'Event restored' : 'Event cancelled'),
    invalidate,
  });
  const del = useAction((ev: ServiceEvent) => api.del(`/api/events/${ev.id}`), {
    success: 'Event deleted',
    invalidate,
    onSuccess: () => setDeleting(null),
  });
  const tz = campus.timezone;

  return (
    <Card
      title="Special & holiday events"
      actions={
        <>
          <Checkbox checked={includePast} onChange={setIncludePast} label="Show past" />
          {isAdmin && (
            <Button variant="primary" size="sm" onClick={() => setEditing('new')}>
              + Add event
            </Button>
          )}
        </>
      }
    >
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <ErrorBox error={q.error} />
      ) : q.data.length === 0 ? (
        <Empty>No one-time events.</Empty>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Name</Th>
              <Th>Kind</Th>
              <Th>When ({zoneAbbr(tz)})</Th>
              <Th>Early access</Th>
              <Th>Status</Th>
              {isAdmin && <Th />}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {q.data.map((ev) => (
              <tr key={ev.id} className={ev.cancelled ? 'opacity-60' : undefined}>
                <Td className="font-medium">{ev.name}</Td>
                <Td>
                  <KindBadge kind={ev.kind} />
                </Td>
                <Td className="whitespace-nowrap">
                  {formatInZone(ev.start_at, tz, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })} –{' '}
                  {formatTime(ev.end_at, tz)}
                </Td>
                <Td>{ev.early_access_minutes} min</Td>
                <Td>{ev.cancelled ? <Badge tone="red">Cancelled</Badge> : <Badge tone="green">Scheduled</Badge>}</Td>
                {isAdmin && (
                  <Td className="whitespace-nowrap text-right">
                    {ev.kind !== 'manual' && (
                      <Button size="sm" variant="ghost" onClick={() => setEditing(ev)}>
                        Edit
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => cancel.mutate(ev)}>
                      {ev.cancelled ? 'Restore' : 'Cancel'}
                    </Button>
                    <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setDeleting(ev)}>
                      Delete
                    </Button>
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {editing && <EventModal campus={campus} languages={languages} initial={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={!!deleting}
        title="Delete event?"
        message={`"${deleting?.name}" will be permanently removed.`}
        confirmLabel="Delete"
        busy={del.isPending}
        onConfirm={() => deleting && del.mutate(deleting)}
        onCancel={() => setDeleting(null)}
      />
    </Card>
  );
}

function OccurrencesSection({ campus }: { campus: Campus }) {
  const q = useQuery({
    queryKey: occKey(campus.id),
    queryFn: () => api.get<Occurrence[]>(`/api/campuses/${campus.id}/occurrences?days=14`),
    refetchInterval: 60_000,
  });
  const [confirming, setConfirming] = useState<Occurrence | null>(null);
  const invalidate = [occKey(campus.id), eventKey(campus.id)];
  const cancel = useAction((key: string) => api.post('/api/occurrences/cancel', { key }), {
    success: 'Occurrence cancelled',
    invalidate,
    onSuccess: () => setConfirming(null),
  });
  const restore = useAction((key: string) => api.post('/api/occurrences/restore', { key }), { success: 'Occurrence restored', invalidate });
  const tz = campus.timezone;
  const now = Date.now();

  return (
    <Card title="Upcoming occurrences (next 14 days)">
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <ErrorBox error={q.error} />
      ) : q.data.length === 0 ? (
        <Empty>Nothing scheduled in the next 14 days.</Empty>
      ) : (
        <ul className="divide-y divide-gray-100">
          {q.data.map((o) => {
            const live = Date.parse(o.window_start) <= now && now < Date.parse(o.end) && !o.cancelled;
            return (
              <li key={o.key} className="flex flex-wrap items-center gap-3 py-2.5">
                <div className="w-44 shrink-0 text-sm">
                  <div className="font-medium text-gray-900">{formatInZone(o.start, tz, { weekday: 'short', month: 'short', day: 'numeric' })}</div>
                  <div className="text-xs text-gray-500">
                    {formatTime(o.start, tz)} – {formatTime(o.end, tz)} {zoneAbbr(tz, Date.parse(o.start))}
                  </div>
                </div>
                <div className={o.cancelled ? 'flex-1 text-sm text-gray-400 line-through' : 'flex-1 text-sm text-gray-800'}>{o.name}</div>
                <KindBadge kind={o.kind} />
                {live && <Badge tone="green" dot>Live window</Badge>}
                {o.cancelled ? (
                  <>
                    <Badge tone="red">Cancelled</Badge>
                    <Button size="sm" onClick={() => restore.mutate(o.key)} loading={restore.isPending && restore.variables === o.key}>
                      Restore
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setConfirming(o)}>
                    Cancel
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <ConfirmDialog
        open={!!confirming}
        title="Cancel this occurrence?"
        message={
          confirming && (
            <>
              <strong>{confirming.name}</strong> on {formatInZone(confirming.start, tz)} will not be captioned. You can restore it later.
            </>
          )
        }
        confirmLabel="Cancel occurrence"
        busy={cancel.isPending}
        onConfirm={() => confirming && cancel.mutate(confirming.key)}
        onCancel={() => setConfirming(null)}
      />
    </Card>
  );
}

export function SchedulePage() {
  const campuses = useCampuses();
  const languages = useLanguages();
  const [campus, setCampus] = useSelectedCampus(campuses.data);

  if (campuses.isPending || languages.isPending) return <Loading />;
  if (campuses.isError) return <ErrorBox error={campuses.error} />;
  if (languages.isError) return <ErrorBox error={languages.error} />;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Services & schedule"
        description={campus ? `Times shown in ${campus.timezone}.` : undefined}
        actions={campus && <CampusSelect campuses={campuses.data} value={campus.id} onChange={setCampus} />}
      />
      {!campus ? (
        <Empty>Create a campus first.</Empty>
      ) : (
        <>
          <OccurrencesSection campus={campus} />
          <SchedulesSection campus={campus} languages={languages.data} />
          <EventsSection campus={campus} languages={languages.data} />
        </>
      )}
    </div>
  );
}
