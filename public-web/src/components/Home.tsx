import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useConfig } from "../hooks/useConfig";
import i18n, { isRtlUi } from "../i18n";
import { applyDocumentLanguage } from "../lib/language";
import { Loading } from "./Loading";
import { Logo } from "./Logo";
import { Message, WaitingDots } from "./Message";

export function Home({ onSingleCampus }: { onSingleCampus: (slug: string) => void }) {
  const { t } = useTranslation();
  const config = useConfig();
  const campuses = config.kind === "ok" ? config.config.campuses : [];
  const only = campuses.length === 1 ? campuses[0] : undefined;

  useEffect(() => {
    applyDocumentLanguage(i18n.language, isRtlUi(i18n.language));
    document.title = t("app.title");
  }, [t]);

  useEffect(() => {
    if (only) onSingleCampus(only.slug);
  }, [only, onSingleCampus]);

  if (config.kind === "loading" || only) return <Loading />;

  const churchName = config.kind === "ok" ? config.config.church_name : "";

  return (
    <main className="mx-auto flex min-h-[100dvh] max-w-lg flex-col px-5 py-10">
      <div className="flex justify-center">
        <Logo churchName={churchName} size="lg" />
      </div>
      {config.kind === "error" ? (
        <div className="text-2xl">
          <Message title={t("errors.retrying")}>
            <WaitingDots />
          </Message>
        </div>
      ) : campuses.length === 0 ? (
        <div className="text-2xl">
          <Message title={t("errors.noCampuses")} />
        </div>
      ) : (
        <>
          <h1 className="mt-8 text-center text-3xl font-bold text-gray-900">{t("campus.chooseTitle")}</h1>
          <ul className="mt-8 space-y-3">
            {campuses.map((c) => (
              <li key={c.slug}>
                <a
                  href={`/${encodeURIComponent(c.slug)}`}
                  className="flex min-h-14 items-center justify-between rounded-2xl border-2 border-gray-200 px-5 py-3 text-xl font-medium text-gray-900 hover:border-brand-600 hover:bg-brand-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-500/60"
                >
                  <span>{c.name}</span>
                  <span aria-hidden="true" className="text-gray-400 rtl:-scale-x-100">
                    →
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
