import { useCallback, useEffect, useRef, useState } from "react";
import { fetchStatus } from "../lib/api";
import { clockOffsetMs, nextPollDelay } from "../lib/time";
import type { CampusStatus } from "../lib/types";

export interface CampusStatusState {
  status: CampusStatus | null;
  loaded: boolean;
  notFound: boolean;
  failures: number;
  offsetMs: number;
}

export interface CampusStatusApi extends CampusStatusState {
  refresh: () => Promise<CampusStatus | null>;
  applyStatus: (status: CampusStatus) => void;
}

const INITIAL: CampusStatusState = { status: null, loaded: false, notFound: false, failures: 0, offsetMs: 0 };

export function useCampusStatus(slug: string, wantsStream: boolean): CampusStatusApi {
  const [state, setState] = useState<CampusStatusState>(INITIAL);
  const retryAfterRef = useRef(0);
  const seqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const applyStatus = useCallback((status: CampusStatus) => {
    seqRef.current += 1;
    retryAfterRef.current = 0;
    setState({
      status,
      loaded: true,
      notFound: false,
      failures: 0,
      offsetMs: clockOffsetMs(status.server_time, Date.now()),
    });
  }, []);

  const refresh = useCallback(async (): Promise<CampusStatus | null> => {
    const seq = ++seqRef.current;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const result = await fetchStatus(slug, ctrl.signal);
      if (seq !== seqRef.current) return null;
      if (result.kind === "ok") {
        retryAfterRef.current = 0;
        setState({
          status: result.status,
          loaded: true,
          notFound: false,
          failures: 0,
          offsetMs: clockOffsetMs(result.status.server_time, Date.now()),
        });
        return result.status;
      }
      if (result.kind === "notfound") {
        setState((s) => ({ ...s, loaded: true, notFound: true, failures: 0 }));
        return null;
      }
      retryAfterRef.current = result.retryAfterMs;
      setState((s) => ({
        ...s,
        loaded: true,
        notFound: false,
        failures: s.failures + 1,
        offsetMs: result.status ? clockOffsetMs(result.status.server_time, Date.now()) : s.offsetMs,
      }));
      return null;
    } catch {
      if (seq !== seqRef.current || ctrl.signal.aborted) return null;
      retryAfterRef.current = 0;
      setState((s) => ({ ...s, loaded: true, failures: s.failures + 1 }));
      return null;
    }
  }, [slug]);

  useEffect(() => {
    setState(INITIAL);
    void refresh();
    return () => abortRef.current?.abort();
  }, [refresh]);

  const streaming = wantsStream && state.status?.phase === "live";

  useEffect(() => {
    if (!state.loaded || state.notFound) return;
    const delay = nextPollDelay({
      status: state.status,
      failures: state.failures,
      retryAfterMs: retryAfterRef.current,
      streaming,
      serverNowMs: Date.now() + state.offsetMs,
      random: Math.random(),
    });
    if (delay === null) return;
    const id = window.setTimeout(() => void refresh(), delay);
    return () => window.clearTimeout(id);
  }, [state, streaming, refresh]);

  useEffect(() => {
    if (streaming || state.notFound) return;
    const wake = () => {
      if (document.visibilityState === "visible" && navigator.onLine) void refresh();
    };
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", wake);
    return () => {
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", wake);
    };
  }, [streaming, state.notFound, refresh]);

  return { ...state, refresh, applyStatus };
}
