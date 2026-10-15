import type { Language } from "./types";

function baseOf(code: string): string {
  return code.toLowerCase().split("-")[0] ?? code.toLowerCase();
}

export function matchOffered(candidate: string | null | undefined, offered: Language[]): string | null {
  if (!candidate) return null;
  const lower = candidate.toLowerCase();
  const exact = offered.find((l) => l.code.toLowerCase() === lower);
  if (exact) return exact.code;
  const base = baseOf(candidate);
  const byBase = offered.find((l) => l.code.toLowerCase() === base) ?? offered.find((l) => baseOf(l.code) === base);
  return byBase ? byBase.code : null;
}

export function browserLanguages(): string[] {
  if (typeof navigator === "undefined") return [];
  if (Array.isArray(navigator.languages) && navigator.languages.length) return [...navigator.languages];
  return navigator.language ? [navigator.language] : [];
}

export function pickDefaultLanguage(
  offered: Language[],
  saved: string | null,
  browser: string[],
  campusDefault: string | null | undefined,
): string | null {
  if (!offered.length) return null;
  const fromSaved = matchOffered(saved, offered);
  if (fromSaved) return fromSaved;
  for (const b of browser) {
    const m = matchOffered(b, offered);
    if (m) return m;
  }
  return matchOffered(campusDefault, offered) ?? offered[0]?.code ?? null;
}

export function applyDocumentLanguage(code: string, rtl: boolean): void {
  const html = document.documentElement;
  html.lang = code;
  html.dir = rtl ? "rtl" : "ltr";
}

export function formatDateTime(iso: string, lang: string, timeZone: string | undefined): string {
  const date = new Date(iso);
  const opts: Intl.DateTimeFormatOptions = { weekday: "long", hour: "numeric", minute: "2-digit", timeZone };
  try {
    return new Intl.DateTimeFormat(lang, opts).format(date);
  } catch {
    try {
      return new Intl.DateTimeFormat("en", { ...opts, timeZone: undefined }).format(date);
    } catch {
      return date.toLocaleString();
    }
  }
}
