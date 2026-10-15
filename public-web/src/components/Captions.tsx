import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { CaptionState } from "../lib/captions";

interface Props {
  captions: CaptionState;
  sizeClass: string;
}

const BOTTOM_THRESHOLD_PX = 40;

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function Captions({ captions, sizeClass }: Props) {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastTopRef = useRef(0);
  const [follow, setFollow] = useState(true);

  const scrollToBottom = useCallback((smooth: boolean) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth && !prefersReducedMotion() ? "smooth" : "auto" });
  }, []);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distance <= BOTTOM_THRESHOLD_PX) setFollow(true);
    else if (el.scrollTop < lastTopRef.current - 2) setFollow(false);
    lastTopRef.current = el.scrollTop;
  };

  useLayoutEffect(() => {
    if (follow) scrollToBottom(true);
  }, [captions.finals, captions.partial, follow, scrollToBottom]);

  useEffect(() => {
    if (follow) scrollToBottom(false);
  }, [sizeClass]);

  const jumpToLive = () => {
    setFollow(true);
    scrollToBottom(true);
  };

  const empty = captions.finals.length === 0 && !captions.partial;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {captions.translationUnavailable && (
        <div
          role="status"
          className="shrink-0 border-b border-amber-200 bg-amber-50 px-5 py-2 text-center text-sm text-amber-900"
        >
          {t("captions.translationUnavailable")}
        </div>
      )}
      <div className="relative min-h-0 flex-1">
      <div ref={scrollRef} onScroll={onScroll} className="h-full overflow-y-auto overscroll-contain px-5 pb-24 pt-6">
        <div className={`mx-auto max-w-3xl text-start text-gray-900 ${sizeClass}`}>
          {empty && <p className="text-gray-400">{t("captions.empty")}</p>}
          <div role="log" aria-live="polite" aria-relevant="additions" aria-label={t("captions.regionLabel")}>
            {captions.finals.map((line) => (
              <p key={line.id} className="mb-4">
                {line.text}
              </p>
            ))}
          </div>
          {captions.partial && (
            <p aria-hidden="true" className="mb-4 text-gray-500">
              {captions.partial.text}
            </p>
          )}
        </div>
      </div>
      {!follow && (
        <div className="pointer-events-none absolute inset-x-0 bottom-5 flex justify-center">
          <button
            type="button"
            onClick={jumpToLive}
            className="pointer-events-auto inline-flex min-h-11 items-center gap-2 rounded-full bg-gray-900 px-5 py-2 text-base font-semibold text-white shadow-lg hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-500/60"
          >
            <span aria-hidden="true">↓</span>
            {t("captions.jumpToLive")}
          </button>
        </div>
      )}
      </div>
    </div>
  );
}
