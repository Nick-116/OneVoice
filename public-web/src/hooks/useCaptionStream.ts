import { useEffect, useReducer, useState } from "react";
import { streamUrl } from "../lib/api";
import { captionReducer, initialCaptionState, type CaptionState } from "../lib/captions";
import { isCampusStatus, isCaptionMessage, isNoticeMessage, parseJson } from "../lib/guards";
import { backoffMs } from "../lib/time";
import type { CampusStatus } from "../lib/types";
import { useLatest } from "./useLatest";

export type StreamConnection = "idle" | "connecting" | "open";

interface Options {
  slug: string;
  lang: string | null;
  enabled: boolean;
  serviceKey: string | null;
  onStatus: (status: CampusStatus) => void;
  refreshStatus: () => Promise<CampusStatus | null>;
}

const STALE_AFTER_HIDDEN_MS = 20_000;

export function useCaptionStream(opts: Options): { captions: CaptionState; connection: StreamConnection } {
  const { slug, lang, enabled, serviceKey } = opts;
  const [captions, dispatch] = useReducer(captionReducer, initialCaptionState);
  const [connection, setConnection] = useState<StreamConnection>("idle");
  const onStatus = useLatest(opts.onStatus);
  const refreshStatus = useLatest(opts.refreshStatus);

  useEffect(() => {
    if (serviceKey) dispatch({ type: "occ", occ: serviceKey });
  }, [serviceKey]);

  useEffect(() => {
    dispatch({ type: "reset" });
  }, [lang]);

  useEffect(() => {
    if (!enabled || !lang) {
      setConnection("idle");
      return;
    }
    let disposed = false;
    let source: EventSource | null = null;
    let retryTimer: number | undefined;
    let attempt = 0;
    let hiddenAt = 0;

    const close = () => {
      source?.close();
      source = null;
    };
    const clearRetry = () => {
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      retryTimer = undefined;
    };

    const scheduleRetry = () => {
      if (disposed) return;
      clearRetry();
      setConnection("connecting");
      const delay = backoffMs(attempt++, 1000, 15_000, Math.random());
      retryTimer = window.setTimeout(async () => {
        retryTimer = undefined;
        const status = await refreshStatus.current().catch(() => null);
        if (disposed) return;
        if (!status) scheduleRetry();
        else if (status.phase === "live") connect();
        else setConnection("idle");
      }, delay);
    };

    const connect = () => {
      close();
      clearRetry();
      if (disposed) return;
      setConnection("connecting");
      const es = new EventSource(streamUrl(slug, lang));
      source = es;
      es.onopen = () => {
        if (source !== es) return;
        attempt = 0;
        setConnection("open");
      };
      es.onerror = () => {
        if (source !== es) return;
        close();
        scheduleRetry();
      };
      es.addEventListener("status", (ev) => {
        if (source !== es) return;
        const status = parseJson((ev as MessageEvent<string>).data);
        if (!isCampusStatus(status)) return;
        if (status.phase === "live" && status.service?.key) dispatch({ type: "occ", occ: status.service.key });
        onStatus.current(status);
        if (status.phase !== "live") {
          close();
          setConnection("idle");
        }
      });
      es.addEventListener("backlog", (ev) => {
        if (source !== es) return;
        const list = parseJson((ev as MessageEvent<string>).data);
        if (Array.isArray(list)) dispatch({ type: "backlog", messages: list.filter(isCaptionMessage) });
      });
      es.addEventListener("caption", (ev) => {
        if (source !== es) return;
        const msg = parseJson((ev as MessageEvent<string>).data);
        if (isCaptionMessage(msg)) dispatch({ type: "caption", message: msg });
        else if (isNoticeMessage(msg) && (!msg.lang || msg.lang === lang)) dispatch({ type: "notice", message: msg });
      });
    };

    const reconnectNow = () => {
      if (disposed) return;
      attempt = 0;
      connect();
    };
    const onOnline = () => reconnectNow();
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        hiddenAt = Date.now();
        return;
      }
      const stale = hiddenAt > 0 && Date.now() - hiddenAt > STALE_AFTER_HIDDEN_MS;
      if (!source || source.readyState !== EventSource.OPEN || stale) reconnectNow();
    };

    window.addEventListener("online", onOnline);
    document.addEventListener("visibilitychange", onVisibility);
    connect();

    return () => {
      disposed = true;
      close();
      clearRetry();
      window.removeEventListener("online", onOnline);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, slug, lang, onStatus, refreshStatus]);

  return { captions, connection };
}
