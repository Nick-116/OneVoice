import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { api } from '../api';
import { Badge, Card, Empty, ErrorBox, Input, Loading, PageHeader, Select, Table, Td, Th } from '../components/ui';
import { useCampuses, useNow } from '../lib/queries';
import { formatInZone, relativeTime } from '../lib/time';
import type { AuditEntry, ErrorEntry } from '../types';

function detailsText(d: Record<string, unknown> | null): string {
  if (!d || Object.keys(d).length === 0) return '';
  return Object.entries(d)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' · ');
}

export function AuditPage() {
  const [limit, setLimit] = useState(200);
  const [filter, setFilter] = useState('');
  const q = useQuery({ queryKey: ['audit', limit], queryFn: () => api.get<AuditEntry[]>(`/api/audit?limit=${limit}`) });
  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!q.data || !f) return q.data ?? [];
    return q.data.filter((a) => [a.username, a.action, a.target, a.ip ?? '', detailsText(a.details)].join(' ').toLowerCase().includes(f));
  }, [q.data, filter]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Audit log"
        description="Every sign-in and configuration change."
        actions={
          <>
            <Input type="search" placeholder="Filter…" aria-label="Filter audit log" className="w-48" value={filter} onChange={(e) => setFilter(e.target.value)} />
            <Select value={limit} onChange={(e) => setLimit(Number(e.target.value))} aria-label="Number of entries" className="w-32">
              <option value={200}>Last 200</option>
              <option value={500}>Last 500</option>
              <option value={1000}>Last 1000</option>
            </Select>
          </>
        }
      />
      <Card>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorBox error={q.error} />
        ) : rows.length === 0 ? (
          <Empty>No entries.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>When</Th>
                <Th>User</Th>
                <Th>Action</Th>
                <Th>Target</Th>
                <Th>Details</Th>
                <Th>IP</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((a, i) => (
                <tr key={`${a.at}-${i}`}>
                  <Td className="whitespace-nowrap text-xs">{formatInZone(a.at)}</Td>
                  <Td>{a.username || <span className="text-gray-400">system</span>}</Td>
                  <Td>
                    <Badge tone={a.action.includes('deleted') || a.action.includes('revoked') ? 'red' : a.action.includes('login') || a.action.includes('mfa') ? 'gray' : 'indigo'}>
                      {a.action}
                    </Badge>
                  </Td>
                  <Td className="max-w-[12rem] break-words text-xs">{a.target}</Td>
                  <Td className="max-w-md break-words text-xs text-gray-600">{detailsText(a.details)}</Td>
                  <Td className="font-mono text-xs">{a.ip}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

export function ErrorsPage() {
  const q = useQuery({ queryKey: ['errors'], queryFn: () => api.get<ErrorEntry[]>('/api/errors?limit=200'), refetchInterval: 10_000 });
  const campuses = useCampuses();
  const now = useNow(5000);
  const [component, setComponent] = useState('');
  const components = useMemo(() => Array.from(new Set((q.data ?? []).map((e) => e.component))).sort(), [q.data]);
  const rows = (q.data ?? []).filter((e) => !component || e.component === component);
  const campusName = (id: number | null) => (id == null ? '—' : campuses.data?.find((c) => c.id === id)?.name ?? `#${id}`);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Errors"
        description="The 200 most recent errors from the worker, ingest and providers · refreshes every 10 s"
        actions={
          <Select value={component} onChange={(e) => setComponent(e.target.value)} aria-label="Component" className="w-44">
            <option value="">All components</option>
            {components.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        }
      />
      <Card>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorBox error={q.error} />
        ) : rows.length === 0 ? (
          <Empty>No errors recorded.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>When</Th>
                <Th>Component</Th>
                <Th>Campus</Th>
                <Th>Message</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((e, i) => (
                <tr key={`${e.at}-${i}`}>
                  <Td className="whitespace-nowrap text-xs">
                    <div>{relativeTime(e.at, now)}</div>
                    <div className="text-gray-500">{formatInZone(e.at)}</div>
                  </Td>
                  <Td>
                    <Badge tone="red">{e.component}</Badge>
                  </Td>
                  <Td className="text-xs">{campusName(e.campus_id)}</Td>
                  <Td className="break-words font-mono text-xs">{e.message}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
