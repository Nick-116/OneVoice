import { useTranslation } from "react-i18next";
import { useNow } from "../hooks/useNow";
import { formatDateTime } from "../lib/language";
import { countdownView, parseIsoMs } from "../lib/time";
import type { NextService } from "../lib/types";
import { Message } from "./Message";

interface Props {
  next: NextService;
  offsetMs: number;
  lang: string;
  timeZone: string | undefined;
}

export function Countdown({ next, offsetMs, lang, timeZone }: Props) {
  const { t } = useTranslation();
  const now = useNow(offsetMs);
  const startMs = parseIsoMs(next.start) ?? now;
  const view = countdownView(startMs - now);

  if (view.kind === "soon") return <Message title={t("schedule.aboutToBegin")} />;
  if (view.kind === "minutes") {
    return <Message title={t("schedule.startsInMinutes", { count: view.minutes })} />;
  }
  return (
    <Message title={t("schedule.nextService")}>
      <p className="text-gray-700">
        <time dateTime={next.start}>{formatDateTime(next.start, lang, timeZone)}</time>
      </p>
      <p
        className="font-semibold tabular-nums tracking-wider text-gray-900"
        dir="ltr"
        aria-label={t("schedule.countdownLabel")}
        role="timer"
      >
        {view.hms}
      </p>
    </Message>
  );
}
