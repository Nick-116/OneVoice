import { cx } from './ui';

/** OneVoice product mark (the church's own branding is only used on the public caption site). */
export function Brand({ size = 'md', dark = false }: { size?: 'md' | 'lg'; dark?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <img src="/onevoice-icon.svg" alt="" className={size === 'lg' ? 'h-12 w-12' : 'h-8 w-8'} />
      <span className={cx('font-bold tracking-tight', size === 'lg' ? 'text-2xl' : 'text-base', dark ? 'text-white' : 'text-indigo-950')}>
        One<span className={dark ? 'text-violet-300' : 'text-violet-600'}>Voice</span>
      </span>
    </span>
  );
}
