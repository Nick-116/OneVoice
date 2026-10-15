import { useTranslation } from "react-i18next";

export type PillKind = "live" | "connecting" | "waiting" | "offline" | "notLive";

const STYLES: Record<PillKind, { pill: string; dot: string }> = {
  live: { pill: "bg-green-50 text-green-800 ring-green-600/30", dot: "bg-green-600 motion-safe:animate-pulse" },
  connecting: { pill: "bg-amber-50 text-amber-900 ring-amber-600/30", dot: "bg-amber-500" },
  waiting: { pill: "bg-amber-50 text-amber-900 ring-amber-600/30", dot: "bg-amber-500" },
  offline: { pill: "bg-gray-100 text-gray-700 ring-gray-400/40", dot: "bg-gray-400" },
  notLive: { pill: "bg-gray-100 text-gray-700 ring-gray-400/40", dot: "bg-gray-400" },
};

export function StatusPill({ kind }: { kind: PillKind }) {
  const { t } = useTranslation();
  const style = STYLES[kind];
  return (
    <span
      role="status"
      className={`inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full px-3 py-1 text-sm font-medium ring-1 ring-inset ${style.pill}`}
    >
      <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${style.dot}`} />
      {t(`status.${kind}`)}
    </span>
  );
}
