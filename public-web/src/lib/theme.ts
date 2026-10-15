import { useSyncExternalStore } from "react";
import { fontStack } from "./fonts";
import { readStorage, writeStorage } from "./storage";

/** Accent palette chosen in the admin dashboard (contrast-safe shades computed by the server). */
export type Theme = Partial<Record<"50" | "100" | "500" | "600" | "700" | "800", string>>;

export type Fonts = { body?: string; name?: string };

const THEME_KEY = "cc.theme";
const FONTS_KEY = "cc.fonts";
const HEX = /^#[0-9a-fA-F]{6}$/;
const SHADES = ["50", "100", "500", "600", "700", "800"] as const;

function channels(hex: string): string {
  return `${parseInt(hex.slice(1, 3), 16)} ${parseInt(hex.slice(3, 5), 16)} ${parseInt(hex.slice(5, 7), 16)}`;
}

/** Sets the --brand-* CSS variables that Tailwind's `brand` colors read. */
export function applyTheme(theme: Theme | null | undefined, persist = true): void {
  if (!theme) return;
  const style = document.documentElement.style;
  for (const shade of SHADES) {
    const value = theme[shade];
    if (value && HEX.test(value)) style.setProperty(`--brand-${shade}`, channels(value));
  }
  if (persist) writeStorage(THEME_KEY, JSON.stringify(theme));
}

/** Sets --font-body (captions and interface) and --font-name (church name). */
export function applyFonts(fonts: Fonts | null | undefined, persist = true): void {
  if (!fonts) return;
  const style = document.documentElement.style;
  style.setProperty("--font-body", fontStack(fonts.body));
  style.setProperty("--font-name", fontStack(fonts.name));
  if (persist) writeStorage(FONTS_KEY, JSON.stringify(fonts));
}

/** Re-apply the last theme and fonts seen on this phone before the network answers (no flash). */
export function restoreTheme(): void {
  try {
    const theme = readStorage(THEME_KEY);
    if (theme) applyTheme(JSON.parse(theme) as Theme, false);
    const fonts = readStorage(FONTS_KEY);
    if (fonts) applyFonts(JSON.parse(fonts) as Fonts, false);
  } catch {
    /* ignore corrupt values */
  }
}

// Logo version: a content hash from the server, used to cache-bust the logo URL.
let logoVersion: string | null = null;
const listeners = new Set<() => void>();

export function setLogoVersion(v: string | null | undefined): void {
  const next = v && /^[0-9a-f]{8,64}$/.test(v) ? v : null;
  if (next === logoVersion) return;
  logoVersion = next;
  listeners.forEach((l) => l());
}

export function useLogoUrl(): string {
  const v = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => logoVersion,
  );
  return v ? `/branding/logo?v=${v}` : "/branding/logo";
}
