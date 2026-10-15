import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import ar from "./locales/ar.json";
import en from "./locales/en.json";
import es from "./locales/es.json";
import fr from "./locales/fr.json";
import hi from "./locales/hi.json";
import ht from "./locales/ht.json";
import ko from "./locales/ko.json";
import pt from "./locales/pt.json";
import ru from "./locales/ru.json";
import uk from "./locales/uk.json";
import vi from "./locales/vi.json";
import zh from "./locales/zh.json";
import { browserLanguages } from "./lib/language";
import { readStorage } from "./lib/storage";

export const locales = { en, es, pt, fr, ht, zh, ko, ar, ru, uk, vi, hi } as const;
export type UiLanguage = keyof typeof locales;

const RTL_UI = new Set(["ar"]);

export function uiLanguageFor(code: string): UiLanguage {
  const lower = code.toLowerCase();
  if (lower in locales) return lower as UiLanguage;
  const base = lower.split("-")[0] ?? "";
  return base in locales ? (base as UiLanguage) : "en";
}

export function isRtlUi(code: string): boolean {
  return RTL_UI.has(uiLanguageFor(code));
}

function initialLanguage(): UiLanguage {
  const saved = readStorage("cc.lang");
  if (saved && uiLanguageFor(saved) !== "en") return uiLanguageFor(saved);
  for (const b of browserLanguages()) {
    const ui = uiLanguageFor(b);
    if (ui !== "en" || b.toLowerCase().startsWith("en")) return ui;
  }
  return "en";
}

export function setUiLanguage(code: string): void {
  const ui = uiLanguageFor(code);
  if (i18n.language !== ui) void i18n.changeLanguage(ui);
}

void i18n.use(initReactI18next).init({
  resources: Object.fromEntries(Object.entries(locales).map(([k, v]) => [k, { translation: v }])),
  lng: initialLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
  react: { useSuspense: false },
});

export default i18n;
