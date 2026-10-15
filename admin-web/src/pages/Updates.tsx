import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, api } from '../api';
import { Badge, Button, Card, ConfirmDialog, Empty, ErrorBox, Loading, PageHeader, StatusDot } from '../components/ui';
import { useAction } from '../lib/queries';
import type { UpdatesState } from '../types';

const updatesKey = ['updates'] as const;
const BUSY = new Set(['checking', 'updating', 'rolling_back']);

function short(sha?: string | null): string {
  return sha ? sha.slice(0, 7) : '—';
}

function when(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function UpdatesPage() {
  const [confirm, setConfirm] = useState<'none' | 'normal' | 'live'>('none');
  const q = useQuery({
    queryKey: updatesKey,
    queryFn: () => api.get<UpdatesState>('/api/updates'),
    // Poll fast while something is happening; the dashboard itself restarts during an update.
    refetchInterval: (query) => (BUSY.has(query.state.data?.status?.state ?? '') || query.state.data?.pending_request ? 2000 : 10000),
    retry: true,
    retryDelay: 3000,
  });
  const check = useAction(() => api.post('/api/updates/check'), { success: 'Checking GitHub…', invalidate: [updatesKey] });
  const apply = useAction((force: boolean) => api.post('/api/updates/apply', { force }), {
    success: 'Update started. The dashboard will reconnect when it finishes.',
    invalidate: [updatesKey],
    onSuccess: () => setConfirm('none'),
  });

  function install(force: boolean) {
    apply.mutate(force, {
      onError: (e) => {
        if (e instanceof ApiError && e.status === 409 && !force && String(e.message).includes('live')) setConfirm('live');
      },
    });
  }

  if (q.isPending) return <Loading />;
  const data = q.data;
  const st = data?.status ?? null;
  const busy = BUSY.has(st?.state ?? '') || !!data?.pending_request;
  const behind = st?.behind ?? 0;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Updates"
        description={`Install new versions from GitHub (${st?.branch ?? 'main'} branch). The database is backed up first, and a failed update is rolled back automatically.`}
      />
      {q.isError && (
        <Card>
          <p className="text-sm text-amber-800">
            Can’t reach the dashboard right now. If an update is installing, this is expected; it reconnects automatically.
          </p>
          <ErrorBox error={q.error} />
        </Card>
      )}

      {data && (
        <>
          <div className="grid gap-5 md:grid-cols-2">
            <Card title="Installed version">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-gray-500">Version</dt>
                <dd className="font-medium">{data.installed.version}</dd>
                <dt className="text-gray-500">Commit</dt>
                <dd className="font-mono">{short(st?.current_commit ?? data.installed.commit)}</dd>
                <dt className="text-gray-500">Built</dt>
                <dd>{when(data.installed.built_at)}</dd>
              </dl>
            </Card>
            <Card title="Updater">
              <div className="flex items-center gap-2 text-sm">
                <StatusDot tone={data.updater_online ? 'green' : 'red'} pulse={busy} />
                {data.updater_online ? 'Running on the server' : data.updater_installed ? 'Not running' : 'Not installed'}
                {st?.state && <Badge tone={st.state === 'failed' ? 'red' : busy ? 'amber' : 'gray'}>{st.state.replace('_', ' ')}</Badge>}
              </div>
              {st?.message && <p className="mt-2 text-sm text-gray-700">{st.message}</p>}
              <p className="mt-1 text-xs text-gray-500">Last checked: {when(st?.checked_at)}</p>
              {!data.updater_online && (
                <p className="mt-2 text-xs text-gray-600">
                  The updater runs on the server itself (not in the dashboard). See <code>docs/UPDATES.md</code> to install it.
                </p>
              )}
            </Card>
          </div>

          <Card
            title={behind > 0 ? `${behind} update${behind === 1 ? '' : 's'} available` : 'Up to date'}
            actions={
              <div className="flex gap-2">
                <Button onClick={() => check.mutate()} loading={check.isPending} disabled={!data.updater_online || busy}>
                  Check now
                </Button>
                <Button
                  variant="primary"
                  onClick={() => setConfirm('normal')}
                  disabled={!data.updater_online || busy || behind === 0 || !!st?.blocked}
                >
                  Install update
                </Button>
              </div>
            }
          >
            {st?.blocked && <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">{st.blocked}</p>}
            {st?.commits?.length ? (
              <ul className="divide-y divide-gray-100 text-sm">
                {st.commits.map((c) => (
                  <li key={c.sha} className="flex flex-wrap items-baseline gap-x-3 py-2">
                    <code className="text-xs text-gray-500">{c.sha}</code>
                    <span className="flex-1 font-medium text-gray-900">{c.subject}</span>
                    <span className="text-xs text-gray-500">
                      {c.author} · {when(c.date)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No new changes on GitHub.</Empty>
            )}
          </Card>

          <Card title="Updater log">
            {data.log.length ? (
              <pre className="max-h-80 overflow-auto rounded-md bg-gray-900 p-3 text-xs leading-relaxed text-gray-100">{data.log.join('\n')}</pre>
            ) : (
              <Empty>No log yet.</Empty>
            )}
          </Card>
        </>
      )}

      <ConfirmDialog
        open={confirm === 'normal'}
        title="Install update?"
        message="The system restarts while the update installs (usually 2–5 minutes). Phones reconnect automatically. The database is backed up first."
        confirmLabel="Install update"
        tone="primary"
        busy={apply.isPending}
        onConfirm={() => install(false)}
        onCancel={() => setConfirm('none')}
      />
      <ConfirmDialog
        open={confirm === 'live'}
        title="A service is live right now"
        message="Updating now will interrupt live captions for a few minutes. Install anyway?"
        confirmLabel="Update during the service"
        tone="warning"
        busy={apply.isPending}
        onConfirm={() => install(true)}
        onCancel={() => setConfirm('none')}
      />
    </div>
  );
}
