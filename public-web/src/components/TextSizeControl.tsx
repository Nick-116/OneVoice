import { useTranslation } from "react-i18next";
import { TEXT_SIZE_CLASSES } from "../lib/textSize";

interface Props {
  step: number;
  onChange: (step: number) => void;
}

const BTN =
  "inline-flex h-11 min-w-11 items-center justify-center rounded-lg px-3 font-semibold text-gray-900 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-500/60 disabled:text-gray-300 disabled:hover:bg-transparent";

export function TextSizeControl({ step, onChange }: Props) {
  const { t } = useTranslation();
  const max = TEXT_SIZE_CLASSES.length - 1;
  return (
    <div role="group" aria-label={t("textSize.label")} className="flex items-center rounded-xl ring-1 ring-gray-200">
      <button
        type="button"
        className={`${BTN} text-base`}
        onClick={() => onChange(step - 1)}
        disabled={step <= 0}
        aria-label={t("textSize.decrease")}
      >
        <span dir="ltr">A−</span>
      </button>
      <span className="sr-only" aria-live="polite">
        {t("textSize.current", { step: step + 1, total: max + 1 })}
      </span>
      <span aria-hidden="true" className="h-6 w-px bg-gray-200" />
      <button
        type="button"
        className={`${BTN} text-xl`}
        onClick={() => onChange(step + 1)}
        disabled={step >= max}
        aria-label={t("textSize.increase")}
      >
        <span dir="ltr">A+</span>
      </button>
    </div>
  );
}
