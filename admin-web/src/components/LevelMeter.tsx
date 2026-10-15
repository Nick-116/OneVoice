import { cx } from './ui';

const MIN_DB = -60;

function pct(db: number | null | undefined): number {
  if (db === null || db === undefined || !Number.isFinite(db)) return 0;
  return Math.max(0, Math.min(100, ((db - MIN_DB) / -MIN_DB) * 100));
}

function levelColor(db: number | null | undefined): string {
  if (db === null || db === undefined) return 'fill-gray-300';
  if (db > -3) return 'fill-red-500';
  if (db > -9) return 'fill-amber-400';
  return 'fill-green-500';
}

/**
 * Audio level meter (-60 … 0 dBFS) with a peak marker. Drawn in SVG so no inline
 * style attributes are needed (strict CSP).
 */
export function LevelMeter({
  level,
  peak,
  active = true,
  size = 'md',
}: {
  level: number | null | undefined;
  peak: number | null | undefined;
  active?: boolean;
  size?: 'sm' | 'md';
}) {
  const l = active ? pct(level) : 0;
  const p = active ? pct(peak) : 0;
  const label = active && level != null ? `${level.toFixed(1)} dBFS` : 'no signal';
  return (
    <div className="flex items-center gap-2">
      <svg
        viewBox="0 0 100 10"
        preserveAspectRatio="none"
        className={cx('w-full rounded bg-gray-200', size === 'sm' ? 'h-2' : 'h-3')}
        role="meter"
        aria-label="Audio level"
        aria-valuemin={MIN_DB}
        aria-valuemax={0}
        aria-valuenow={active && level != null ? Math.round(level) : MIN_DB}
        aria-valuetext={label}
      >
        {/* reference ticks at -9 and -3 dBFS (amber / red zones) */}
        <rect x={pct(-9)} y="0" width="0.4" height="10" className="fill-gray-400/50" />
        <rect x={pct(-3)} y="0" width="0.4" height="10" className="fill-gray-400/50" />
        <rect x="0" y="0" width={l} height="10" className={cx(levelColor(level), 'transition-all duration-300')} />
        {p > 0 && <rect x={Math.max(0, p - 0.8)} y="0" width="0.8" height="10" className="fill-gray-900" />}
      </svg>
      <span className="w-20 shrink-0 text-right font-mono text-xs tabular-nums text-gray-600">{label}</span>
    </div>
  );
}
