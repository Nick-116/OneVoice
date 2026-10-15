import { useTranslation } from "react-i18next";
import { WaitingDots } from "./Message";

export function Loading() {
  const { t } = useTranslation();
  return (
    <main className="flex min-h-[100dvh] flex-col items-center justify-center gap-4 text-gray-600" aria-busy="true">
      <WaitingDots />
      <p className="text-lg">{t("common.loading")}</p>
    </main>
  );
}
