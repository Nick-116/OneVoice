import { useTranslation } from "react-i18next";
import type { Language } from "../lib/types";
import { Logo } from "./Logo";

interface Props {
  churchName: string;
  languages: Language[];
  selected: string;
  onSelect: (code: string) => void;
  onContinue: (code: string) => void;
}

export function Welcome({ churchName, languages, selected, onSelect, onContinue }: Props) {
  const { t } = useTranslation();
  return (
    <main className="mx-auto flex min-h-[100dvh] max-w-lg flex-col px-5 pb-8 pt-10">
      <div className="flex justify-center">
        <Logo churchName={churchName} size="lg" />
      </div>
      <h1 className="mt-8 text-center text-3xl font-bold text-gray-900">{t("welcome.title")}</h1>
      <p className="mt-3 text-center text-lg text-gray-700">{t("welcome.prompt")}</p>
      <form
        className="mt-8 flex flex-1 flex-col"
        onSubmit={(e) => {
          e.preventDefault();
          onContinue(selected);
        }}
      >
        <fieldset>
          <legend className="sr-only">{t("welcome.languageListLabel")}</legend>
          <ul className="space-y-3">
            {languages.map((lang) => (
              <li key={lang.code}>
                <label className="block cursor-pointer">
                  <input
                    type="radio"
                    name="language"
                    value={lang.code}
                    checked={selected === lang.code}
                    onChange={() => onSelect(lang.code)}
                    className="peer sr-only"
                  />
                  <span
                    className="flex min-h-14 items-center justify-between gap-3 rounded-2xl border-2 border-gray-200 px-5 py-3 text-xl text-gray-900 transition-colors peer-checked:border-brand-600 peer-checked:bg-brand-50 peer-focus-visible:ring-4 peer-focus-visible:ring-brand-500/50 motion-reduce:transition-none"
                  >
                    <span lang={lang.code} dir={lang.rtl ? "rtl" : "ltr"}>
                      {lang.name}
                    </span>
                    <span
                      aria-hidden="true"
                      className={`h-6 w-6 shrink-0 rounded-full border-2 ${
                        selected === lang.code ? "border-brand-600 bg-brand-600 ring-4 ring-inset ring-white" : "border-gray-300"
                      }`}
                    />
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
        <div className="sticky bottom-0 mt-8 bg-white pb-2 pt-4">
          <button
            type="submit"
            className="min-h-14 w-full rounded-2xl bg-brand-700 px-6 text-xl font-semibold text-white hover:bg-brand-800 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-500/60 focus-visible:ring-offset-2"
          >
            {t("welcome.continue")}
          </button>
        </div>
      </form>
    </main>
  );
}
