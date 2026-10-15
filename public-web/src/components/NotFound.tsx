import { useTranslation } from "react-i18next";
import { Message } from "./Message";

export function NotFound() {
  const { t } = useTranslation();
  return (
    <main className="flex min-h-[100dvh] items-center text-2xl">
      <Message title={t("errors.notFound")}>
        <p className="text-lg text-gray-600">{t("errors.notFoundHint")}</p>
        <a
          href="/"
          className="inline-flex min-h-11 items-center rounded-xl px-4 text-lg font-semibold text-brand-700 underline underline-offset-2 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-500/60"
        >
          {t("errors.backToStart")}
        </a>
      </Message>
    </main>
  );
}
