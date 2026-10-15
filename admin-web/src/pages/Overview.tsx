import { useQuery } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { LevelMeter } from '../components/LevelMeter';
import { CaptionBadge, PhaseBadge, SttBadge, translationTone } from '../components/status';
import { Badge, Button, Card, ConfirmDialog, Empty, ErrorBox, Input, Loading, PageHeader, StatusDot, cx } from '../components/ui';
import { keys, useAction, useLanguages, useNow, useSettings } from '../lib/queries';
import { formatDayTime, formatDuration, formatTime, relativeTime } from '../lib/time';
import type { ErrorEntry, LatencySummary, Language, Overview, OverviewCampus } from '../types';

const ms = (s: LatencySummary | undefined) =>
  s && s.p50 != null ? `${Math.round(s.p50)} / ${s.p95 != null ? Math.round(s.p95) : '—'}` : '—';

function StartControls({ item, defaultMinutes }: { item: OverviewCampus; defaultMinutes: number | undefined }) {
  const [minutes, setMinutes] = useState<string>('');
  const [name, setName] = useState('');
  const start = useAction(
    (b: { duration_minutes?: number; name?: string }) => api.post(`/api/campuses/${item.campus.id}/start`, b),
    { success: `Service started at ${item.campus.name}`, invalidate: [keys.overview] },
  );
  const value = minutes === '' ? defaultMinutes ?? 120 : Number(minutes);
  const valid = Number.isFinite(value) && value >= 5 && value <= 720;
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        start.mutate({ duration_minutes: value, ...(name.trim() ? { name: name.trim() } : {}) });
      }}
    >
      <label className="flex flex-col text-xs text-gray-500">
        Duration (min)
        <Input
          type="number"
          min={5}
          max={720}
          className="mt-1 w-24"
          placeholder={String(defaultMinutes ?? 120)}
          value={minutes}
          onChange={(e) => setMinutes(e.target.value)}
        />
      </label>
      <label className="flex min-w-[8rem] flex-1 flex-col text-xs text-gray-500">
        Name (optional)
        <Input className="mt-1" placeholder="Live service" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <Button type="submit" variant="success" size="lg" loading={start.isPending} disabled={!valid || !item.campus.enabled}>
        ▶ Start service now
      </Button>
    </form>
  );
}

function LiveControls({ item }: { item: OverviewCampus }) {
  const [confirm, setConfirm] = useState(false);
  const id = item.campus.id;
  const stop = useAction(() => api.post(`/api/campuses/${id}/stop`), {
    success: `Service stopped at ${item.campus.name}`,
    invalidate: [keys.overview],
    onSuccess: () => setConfirm(false),
  });
  const extend = useAction((minutes: number) => api.post<{ ok: boolean; end: string }>(`/api/campuses/${id}/extend`, { minutes }), {
    success: (r) => `Extended — now ends ${formatTime(r.end, item.campus.timezone)}`,
    invalidate: [keys.overview],
  });
  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="danger" size="lg" onClick={() => setConfirm(true)}>
        ■ Stop service
      </Button>
      <Button variant="secondary" size="lg" loading={extend.isPending && extend.variables === 15} onClick={() => extend.mutate(15)}>
        +15 min
      </Button>
      <Button variant="secondary" size="lg" loading={extend.isPending && extend.variables === 30} onClick={() => extend.mutate(30)}>
        +30 min
      </Button>
      <ConfirmDialog
        open={confirm}
        title={`Stop the service at ${item.campus.name}?`}
        message={
          <>
            Captions will end immediately for all <strong>{Object.values(item.status?.viewers ?? {}).reduce((a, b) => a + b, 0)}</strong> viewers.
            The scheduled service is ended early (or cancelled if it has not started yet).
          </>
        }
        confirmLabel="Stop service"
        busy={stop.isPending}
        onConfirm={() => stop.mutate()}
        onCancel={() => setConfirm(false)}
      />
    </div>
  );
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-0.5 text-sm text-gray-900">{children}</div>
    </div>
  );
}

function CampusCard({ item, now, defaultMinutes, langs }: { item: OverviewCampus; now: number; defaultMinutes?: number; langs?: Language[] }) {
  const { campus, status, audio } = item;
  const tz = campus.timezone;
  const live = status?.phase === 'live';
  const pipe = status?.pipeline ?? null;
  const viewers = status?.viewers ?? {};
  const totalViewers = Object.values(viewers).reduce((a, b) => a + b, 0);
  const langCodes = Array.from(
    new Set([...Object.keys(viewers), ...Object.keys(pipe?.translation ?? {}), ...Object.keys(pipe?.metrics.end_to_end_ms ?? {})]),
  ).sort();
  const name = (c: string) => langs?.find((l) => l.code === c)?.name_en ?? c;

  const service = status?.service;
  const next = status?.next;

  return (
    <article
      className={cx(
        'flex flex-col rounded-lg border bg-white shadow-sm',
        live ? 'border-green-300 ring-1 ring-green-200' : 'border-gray-200',
      )}
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-gray-100 px-4 py-3">
        <h2 className="mr-auto text-base font-semibold text-gray-900">
          {campus.name} <span className="text-xs font-normal text-gray-400">/{campus.slug}</span>
        </h2>
        {!campus.enabled && <Badge tone="gray">Disabled</Badge>}
        <PhaseBadge phase={status?.phase} />
        {live && <CaptionBadge state={status?.captions} />}
      </header>

      <div className="space-y-4 p-4">
        {!status && (
          <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">No status from the worker for this campus yet.</div>
        )}

        {/* service timing */}
        <div className="grid gap-3 sm:grid-cols-2">
          {service ? (
            <Stat label="Current service">
              <span className="font-medium">{service.name}</span>
              <div className="text-xs text-gray-500">
                ends {formatTime(service.end, tz)} · {formatDuration(Date.parse(service.end) - now)} left
              </div>
            </Stat>
          ) : (
            <Stat label="Current service">
              <span className="text-gray-400">None</span>
            </Stat>
          )}
          <Stat label="Next service">
            {next ? (
              <>
                <span className="font-medium">{next.name}</span>
                <div className="text-xs text-gray-500">
                  {formatDayTime(next.start, tz)} · starts {relativeTime(next.start, now)}
                </div>
              </>
            ) : (
              <span className="text-gray-400">None scheduled</span>
            )}
          </Stat>
        </div>

        {/* controls */}
        <div className="rounded-md bg-gray-50 p-3">
          {live ? <LiveControls item={item} /> : <StartControls item={item} defaultMinutes={defaultMinutes} />}
        </div>

        {/* audio */}
        <div>
          <div className="mb-1.5 flex flex-wrap items-center gap-2 text-sm">
            <StatusDot tone={audio.connected ? 'green' : 'red'} pulse={audio.connected} />
            <span className="font-medium">{audio.connected ? 'Audio connected' : 'Audio disconnected'}</span>
            {audio.sender_name && <span className="text-gray-500">· {audio.sender_name}</span>}
            {audio.connected && audio.forwarding && <Badge tone="green">forwarding</Badge>}
            {!audio.connected && audio.last_frame_at && <span className="text-xs text-gray-500">last audio {relativeTime(audio.last_frame_at, now)}</span>}
          </div>
          {audio.local_error && <p className="mb-1.5 text-xs text-red-700">{audio.local_error}</p>}
          <LevelMeter level={audio.level_dbfs} peak={audio.peak_dbfs} active={audio.connected} />
        </div>

        {/* providers */}
        {status && (
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Speech-to-text">
              <span className="flex flex-wrap items-center gap-1.5">
                {status.stt_provider}
                {!status.stt_configured && <Badge tone="red">not configured</Badge>}
                {pipe && <SttBadge state={pipe.stt} />}
              </span>
              {pipe?.stt_error && <div className="mt-1 text-xs text-red-700">{pipe.stt_error}</div>}
            </Stat>
            <Stat label="Translation">
              <span className="flex flex-wrap items-center gap-1.5">
                {status.translation_provider}
                {!status.translation_configured && <Badge tone="red">not configured</Badge>}
              </span>
            </Stat>
            <Stat label="Viewers">
              <span className="text-lg font-semibold tabular-nums">{totalViewers}</span>
              {pipe && <span className="ml-2 text-xs text-gray-500">{pipe.segments} segments</span>}
            </Stat>
          </div>
        )}

        {/* per-language */}
        {langCodes.length > 0 && (
          <div className="-mx-4 overflow-x-auto sm:mx-0">
            <table className="min-w-full whitespace-nowrap text-xs">
              <thead>
                <tr className="text-left text-gray-500">
                  <th className="px-2 py-1 font-medium">Language</th>
                  <th className="px-2 py-1 text-right font-medium">Viewers</th>
                  <th className="px-2 py-1 font-medium">Channel</th>
                  <th className="px-2 py-1 text-right font-medium">Translate p50/p95 ms</th>
                  <th className="px-2 py-1 text-right font-medium">End-to-end p50/p95 ms</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {langCodes.map((c) => {
                  const st = pipe?.translation[c];
                  return (
                    <tr key={c}>
                      <td className="px-2 py-1">{name(c)}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{viewers[c] ?? 0}</td>
                      <td className="px-2 py-1">{st ? <Badge tone={translationTone(st)}>{st}</Badge> : <span className="text-gray-400">—</span>}</td>
                      <td className="px-2 py-1 text-right font-mono tabular-nums">{ms(pipe?.metrics.translate_ms[c])}</td>
                      <td className="px-2 py-1 text-right font-mono tabular-nums">{ms(pipe?.metrics.end_to_end_ms[c])}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {pipe && (
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-600">
            <span>
              STT partial p50/p95: <span className="font-mono">{ms(pipe.metrics.stt_partial_ms)} ms</span>
            </span>
            <span>
              STT final p50/p95: <span className="font-mono">{ms(pipe.metrics.stt_final_ms)} ms</span>
            </span>
            {pipe.last_caption_at && <span>last caption {relativeTime(pipe.last_caption_at, now)}</span>}
          </div>
        )}
      </div>
    </article>
  );
}

function ErrorsList({ errors, campusName, now }: { errors: ErrorEntry[]; campusName: (id: number | null) => string; now: number }) {
  if (!errors.length) return <p className="text-sm text-gray-500">No recent errors.</p>;
  return (
    <ul className="divide-y divide-gray-100 text-sm">
      {errors.map((e, i) => (
        <li key={`${e.at}-${i}`} className="flex flex-col gap-0.5 py-2 sm:flex-row sm:gap-3">
          <span className="w-24 shrink-0 text-xs text-gray-500" title={new Date(e.at * 1000).toLocaleString()}>
            {relativeTime(e.at, now)}
          </span>
          <span className="shrink-0">
            <Badge tone="red">{e.component}</Badge>
            {e.campus_id != null && <span className="ml-1 text-xs text-gray-500">{campusName(e.campus_id)}</span>}
          </span>
          <span className="break-words text-gray-800">{e.message}</span>
        </li>
      ))}
    </ul>
  );
}

export function OverviewPage() {
  const q = useQuery({
    queryKey: keys.overview,
    queryFn: () => api.get<Overview>('/api/overview'),
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  });
  const settings = useSettings();
  const langs = useLanguages();
  const clientNow = useNow(1000);

  if (q.isPending) return <Loading />;
  if (q.isError && !q.data) return <ErrorBox error={q.error} />;
  const data = q.data!;
  // Correct for clock skew between this browser and the server.
  const skew = data.server_time * 1000 - q.dataUpdatedAt;
  const now = clientNow + skew;
  const campusName = (id: number | null) => data.campuses.find((c) => c.campus.id === id)?.campus.name ?? (id == null ? '' : `#${id}`);
  const liveCount = data.campuses.filter((c) => c.status?.phase === 'live').length;

  return (
    <div>
      <PageHeader
        title="Live overview"
        description={`${liveCount} of ${data.campuses.length} campuses live · refreshes every 3 s`}
        actions={
          <>
            <Badge tone={data.worker.alive ? 'green' : 'red'} dot>
              Worker {data.worker.alive ? 'alive' : 'not responding'}
            </Badge>
            <Badge tone="indigo">MTD est. ${data.usage_month.est_cost_usd.toFixed(2)}</Badge>
            {q.isError && <Badge tone="amber">Refresh failed — showing last data</Badge>}
          </>
        }
      />

      {!data.worker.alive && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          The caption worker has not reported a heartbeat
          {data.worker.heartbeat ? ` since ${relativeTime(data.worker.heartbeat, now)}` : ''}. Captions will not run until it is restarted.
        </div>
      )}

      {data.campuses.length === 0 ? (
        <Empty>
          No campuses yet. <Link to="/campuses" className="text-indigo-600 hover:underline">Create one</Link>.
        </Empty>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {data.campuses.map((c) => (
            <CampusCard key={c.campus.id} item={c} now={now} defaultMinutes={settings.data?.manual_default_minutes} langs={langs.data} />
          ))}
        </div>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Recent errors"
          actions={
            <Link to="/errors" className="text-xs font-medium text-indigo-600 hover:underline">
              View all
            </Link>
          }
        >
          <ErrorsList errors={data.recent_errors} campusName={campusName} now={now} />
        </Card>
        <Card title="This month (estimated)">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-gray-500">Speech-to-text</dt>
              <dd className="tabular-nums">{data.usage_month.stt_minutes.toLocaleString()} min</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Translation</dt>
              <dd className="tabular-nums">{data.usage_month.translation_chars.toLocaleString()} chars</dd>
            </div>
            <div className="flex justify-between border-t border-gray-100 pt-2 font-semibold">
              <dt>Estimated cost</dt>
              <dd className="tabular-nums">${data.usage_month.est_cost_usd.toFixed(2)}</dd>
            </div>
          </dl>
          <Link to="/usage" className="mt-3 inline-block text-xs font-medium text-indigo-600 hover:underline">
            Usage details
          </Link>
        </Card>
      </div>
    </div>
  );
}
