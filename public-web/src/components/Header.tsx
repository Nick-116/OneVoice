import { useTranslation } from "react-i18next";
import { Logo } from "./Logo";
import { StatusPill, type PillKind } from "./StatusPill";
import { TextSizeControl } from "./TextSizeControl";

interface Props {
  churchName: string;
  campusName: string;
  languageName: string;
  pill: PillKind;
  textSize: number;
  onTextSize: (step: number) => void;
  onChangeLanguage: () => void;
}

export function Header({ churchName, campusName, languageName, pill, textSize, onTextSize, onChangeLanguage }: Props) {
  const { t } = useTranslation();
  return (
    <header className="shrink-0 border-b border-gray-200 bg-white px-4 pb-2 pt-3">
      <div className="mx-auto flex max-w-3xl items-center gap-3">
        <Logo churchName={churchName} size="sm" />
        <div className="min-w-0 flex-1">
          {churchName && <p className="truncate text-sm font-medium leading-tight text-gray-500">{churchName}</p>}
          <h1 className="line-clamp-2 break-words text-lg font-semibold leading-tight text-gray-900">{campusName}</h1>
        </div>
        <StatusPill kind={pill} />
      </div>
      <div className="mx-auto mt-2 flex max-w-3xl items-center justify-between gap-3">
        <button
          type="button"
          onClick={onChangeLanguage}
          className="-ms-2 inline-flex min-h-11 min-w-0 items-center gap-2 rounded-lg px-2 text-start text-base hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-500/60"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-gray-500" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="9" />
            <path d="M3 12h18M12 3c2.5 2.7 3.75 5.7 3.75 9S14.5 18.3 12 21c-2.5-2.7-3.75-5.7-3.75-9S9.5 5.7 12 3z" />
          </svg>
          <span className="truncate font-semibold text-gray-900">{languageName}</span>
          <span className="truncate text-brand-700 underline underline-offset-2">{t("header.changeLanguage")}</span>
        </button>
        <TextSizeControl step={textSize} onChange={onTextSize} />
      </div>
    </header>
  );
}
