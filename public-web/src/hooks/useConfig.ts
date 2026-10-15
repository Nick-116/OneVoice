import { useEffect, useState } from "react";
import { fetchConfig } from "../lib/api";
import { applyFonts, applyTheme, setLogoVersion } from "../lib/theme";
import { backoffMs } from "../lib/time";
import type { PublicConfig } from "../lib/types";

export type ConfigState = { kind: "loading" } | { kind: "error" } | { kind: "ok"; config: PublicConfig };

export function useConfig(): ConfigState {
  const [state, setState] = useState<ConfigState>({ kind: "loading" });
  useEffect(() => {
    const ctrl = new AbortController();
    let timer: number | undefined;
    let attempt = 0;
    const load = async () => {
      try {
        const config = await fetchConfig(ctrl.signal);
        applyTheme(config.theme);
        applyFonts(config.fonts);
        setLogoVersion(config.logo_version);
        setState({ kind: "ok", config });
      } catch {
        if (ctrl.signal.aborted) return;
        setState((s) => (s.kind === "ok" ? s : { kind: "error" }));
        timer = window.setTimeout(load, backoffMs(attempt++, 2000, 30_000, Math.random()));
      }
    };
    void load();
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, []);
  return state;
}
