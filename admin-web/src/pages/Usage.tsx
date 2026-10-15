import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { api } from '../api';
import { Card, Empty, ErrorBox, Loading, PageHeader, Select, Table, Td, Th } from '../components/ui';
import { useCampuses, useLanguages } from '../lib/queries';
import type { Usage, UsageRow } from '../types';

interface DayAgg {
  day: string;
  sttMinutes: number;
  chars: number;
  sttCost: number;
  trCost: number;
}

function lastNDays(n: number): string[] {
  const out: string[] = [];
  const now = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - i));
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

function aggregateDays(rows: UsageRow[], days: number): DayAgg[] {
  const map = new Map<string, DayAgg>(lastNDays(days).map((d) => [d, { day: d, sttMinutes: 0, chars: 0, sttCost: 0, trCost: 0 }]));
  for (const r of rows) {
    let a = map.get(r.day);
    if (!a) {
      a = { day: r.day, sttMinutes: 0, chars: 0, sttCost: 0, trCost: 0 };
      map.set(r.day, a);
    }
    if (r.metric === 'stt_seconds') {
      a.sttMinutes += r.quantity / 60;
      a.sttCost += r.est_cost_usd;
    } else {
      a.chars += r.quantity;
      a.trCost += r.est_cost_usd;
    }
  }
  return [...map.values()].sort((x, y) => x.day.localeCompare(y.day));
}

function groupBy(rows: UsageRow[], key: (r: UsageRow) => string) {
  const m = new Map<string, { qty: number; cost: number; metric: string }>();
  for (const r of rows) {
    const k = key(r);
    const a = m.get(k) ?? { qty: 0, cost: 0, metric: r.metric };
    a.qty += r.quantity;
    a.cost += r.est_cost_usd;
    m.set(k, a);
  }
  return [...m.entries()].sort((a, b) => b[1].cost - a[1].cost || b[1].qty - a[1].qty);
}

const usd = (n: number) => `$${n.toFixed(n < 10 ? 2 : 2)}`;
const shortDay = (d: string) => new Date(`${d}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });

/** Stacked daily cost bars (STT + translation) — pure SVG, no chart library. */
function CostChart({ days }: { days: DayAgg[] }) {
  const max = Math.max(0.01, ...days.map((d) => d.sttCost + d.trCost));
  const W = 720;
  const H = 180;
  const pad = { l: 44, r: 8, t: 8, b: 22 };
  const bw = (W - pad.l - pad.r) / days.length;
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const ticks = [0, max / 2, max];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-48 w-full" role="img" aria-label="Estimated cost per day">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="stroke-gray-200" strokeWidth="1" />
          <text x={pad.l - 6} y={y(t) + 3} textAnchor="end" className="fill-gray-500 text-[10px]">
            ${t.toFixed(2)}
          </text>
        </g>
      ))}
      {days.map((d, i) => {
        const x = pad.l + i * bw + bw * 0.15;
        const w = bw * 0.7;
        const hs = y(0) - y(d.sttCost);
        const ht = y(0) - y(d.trCost);
        return (
          <g key={d.day}>
            <title>{`${shortDay(d.day)}: STT ${usd(d.sttCost)} (${d.sttMinutes.toFixed(1)} min), translation ${usd(d.trCost)} (${Math.round(d.chars).toLocaleString()} chars)`}</title>
            <rect x={x} y={y(0) - hs} width={w} height={hs} className="fill-indigo-500" />
            <rect x={x} y={y(0) - hs - ht} width={w} height={ht} className="fill-sky-300" />
            {(i % Math.ceil(days.length / 10) === 0 || i === days.length - 1) && (
              <text x={x + w / 2} y={H - 6} textAnchor="middle" className="fill-gray-500 text-[10px]">
                {shortDay(d.day)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export function UsagePage() {
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ['usage', days], queryFn: () => api.get<Usage>(`/api/usage?days=${days}`) });
  const campuses = useCampuses();
  const langs = useLanguages();
  const daily = useMemo(() => (q.data ? aggregateDays(q.data.rows, days) : []), [q.data, days]);

  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const data = q.data;
  const totals = daily.reduce((a, d) => ({ min: a.min + d.sttMinutes, chars: a.chars + d.chars, cost: a.cost + d.sttCost + d.trCost }), { min: 0, chars: 0, cost: 0 });
  const campusName = (id: number) => campuses.data?.find((c) => c.id === id)?.name ?? `#${id}`;
  const langName = (c: string) => (c ? langs.data?.find((l) => l.code === c)?.name_en ?? c : '—');
  const byProvider = groupBy(data.rows, (r) => `${r.provider}|${r.metric}`);
  const byLanguage = groupBy(data.rows.filter((r) => r.metric === 'translation_chars'), (r) => r.language);
  const byCampus = groupBy(data.rows, (r) => String(r.campus_id));
  const fmtQty = (metric: string, q: number) => (metric === 'stt_seconds' ? `${(q / 60).toFixed(1)} min` : `${Math.round(q).toLocaleString()} chars`);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Usage & cost"
        description="Estimates based on the prices configured for each provider. Check your provider invoices for actual charges."
        actions={
          <Select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period" className="w-36">
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </Select>
        }
      />
      <div className="grid gap-4 sm:grid-cols-3">
        {[
          ['Month to date — STT', `${data.month.stt_minutes.toLocaleString()} min`],
          ['Month to date — translation', `${data.month.translation_chars.toLocaleString()} chars`],
          ['Month to date — est. cost', usd(data.month.est_cost_usd)],
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">{value}</div>
          </div>
        ))}
      </div>

      <Card
        title={`Daily estimated cost — last ${days} days (${usd(totals.cost)})`}
        actions={
          <div className="flex gap-3 text-xs text-gray-600">
            <span className="flex items-center gap-1">
              <span className="h-2.5 w-2.5 rounded-sm bg-indigo-500" /> STT
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2.5 w-2.5 rounded-sm bg-sky-300" /> Translation
            </span>
          </div>
        }
      >
        {data.rows.length === 0 ? <Empty>No usage recorded in this period.</Empty> : <CostChart days={daily} />}
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="By provider">
          <Table>
            <thead>
              <tr>
                <Th>Provider</Th>
                <Th className="text-right">Usage</Th>
                <Th className="text-right">Cost</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {byProvider.map(([k, v]) => (
                <tr key={k}>
                  <Td>{k.split('|')[0]}</Td>
                  <Td className="text-right tabular-nums">{fmtQty(v.metric, v.qty)}</Td>
                  <Td className="text-right tabular-nums">{usd(v.cost)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <Card title="Translation by language">
          <Table>
            <thead>
              <tr>
                <Th>Language</Th>
                <Th className="text-right">Characters</Th>
                <Th className="text-right">Cost</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {byLanguage.map(([k, v]) => (
                <tr key={k}>
                  <Td>{langName(k)}</Td>
                  <Td className="text-right tabular-nums">{Math.round(v.qty).toLocaleString()}</Td>
                  <Td className="text-right tabular-nums">{usd(v.cost)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <Card title="By campus">
          <Table>
            <thead>
              <tr>
                <Th>Campus</Th>
                <Th className="text-right">Cost</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {byCampus.map(([k, v]) => (
                <tr key={k}>
                  <Td>{campusName(Number(k))}</Td>
                  <Td className="text-right tabular-nums">{usd(v.cost)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </div>

      <Card title="Daily detail">
        <Table>
          <thead>
            <tr>
              <Th>Day (UTC)</Th>
              <Th className="text-right">STT minutes</Th>
              <Th className="text-right">STT cost</Th>
              <Th className="text-right">Translation chars</Th>
              <Th className="text-right">Translation cost</Th>
              <Th className="text-right">Total</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {[...daily].reverse().filter((d) => d.sttMinutes || d.chars).map((d) => (
              <tr key={d.day}>
                <Td>{shortDay(d.day)}</Td>
                <Td className="text-right tabular-nums">{d.sttMinutes.toFixed(1)}</Td>
                <Td className="text-right tabular-nums">{usd(d.sttCost)}</Td>
                <Td className="text-right tabular-nums">{Math.round(d.chars).toLocaleString()}</Td>
                <Td className="text-right tabular-nums">{usd(d.trCost)}</Td>
                <Td className="text-right font-medium tabular-nums">{usd(d.sttCost + d.trCost)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {!daily.some((d) => d.sttMinutes || d.chars) && <Empty>No usage recorded in this period.</Empty>}
      </Card>
    </div>
  );
}
