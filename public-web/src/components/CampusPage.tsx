import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useCampusStatus } from "../hooks/useCampusStatus";
import { useCaptionStream, type StreamConnection } from "../hooks/useCaptionStream";
import { useConfig } from "../hooks/useConfig";
import { useOnline } from "../hooks/useOnline";
import { useTextSize } from "../hooks/useTextSize";
import { isRtlUi, setUiLanguage } from "../i18n";
import { applyDocumentLanguage, browserLanguages, formatDateTime, matchOffered, pickDefaultLanguage } from "../lib/language";
import { readStorage, writeStorage } from "../lib/storage";
import { TEXT_SIZE_CLASSES } from "../lib/textSize";
import type { CampusStatus, Language } from "../lib/types";
import { Captions } from "./Captions";
import { Countdown } from "./Countdown";
import { Header } from "./Header";
import { Loading } from "./Loading";
import { Logo } from "./Logo";
import { Message, WaitingDots } from "./Message";
import { NotFound } from "./NotFound";
import type { PillKind } from "./StatusPill";
import { Welcome } from "./Welcome";

const NO_LANGUAGES: Language[] = [];

function pillFor(online: boolean, failures: number, status: CampusStatus | null, connection: StreamConnection): PillKind {
  if (!online) return "offline";
  if (failures > 0 || !status || status.phase === "unavailable") return "connecting";
  if (status.phase !== "live") return "notLive";
  if (connection !== "open") return "connecting";
  return status.captions === "live" ? "live" : "waiting";
}

export function CampusPage({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const config = useConfig();
  const churchName = config.kind === "ok" ? config.config.church_name : "";
  const online = useOnline();
  const [textSize, setTextSize] = useTextSize();
  const [saved, setSaved] = useState<string | null>(() => readStorage("cc.lang"));
  const [choosing, setChoosing] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [streamWanted, setStreamWanted] = useState(false);

  const campus = useCampusStatus(slug, streamWanted);
  const { status } = campus;
  const offered = status?.languages ?? NO_LANGUAGES;

  const activeLang = offered.length ? matchOffered(saved, offered) : saved;
  const showWelcome = choosing || !activeLang;
  const welcomeDefault = useMemo(
    () => pickDefaultLanguage(offered, saved, browserLanguages(), status?.default_language),
    [offered, saved, status?.default_language],
  );
  const welcomeLang = (draft && matchOffered(draft, offered)) ?? welcomeDefault;
  const displayLang = (showWelcome ? welcomeLang : activeLang) ?? null;
  const displayInfo = offered.find((l) => l.code === displayLang);

  const streamEnabled = !showWelcome && !!activeLang && status?.phase === "live";
  useEffect(() => setStreamWanted(!showWelcome && !!activeLang), [showWelcome, activeLang]);

  const serviceKey = status?.phase === "live" ? (status.service?.key ?? null) : null;
  const { captions, connection } = useCaptionStream({
    slug,
    lang: activeLang,
    enabled: streamEnabled,
    serviceKey,
    onStatus: campus.applyStatus,
    refreshStatus: campus.refresh,
  });

  useEffect(() => {
    if (!displayLang) return;
    setUiLanguage(displayLang);
    applyDocumentLanguage(displayLang, displayInfo ? displayInfo.rtl : isRtlUi(displayLang));
  }, [displayLang, displayInfo]);

  const campusName = status?.name ?? "";
  useEffect(() => {
    document.title = campusName ? `${t("app.title")} · ${campusName}` : t("app.title");
  }, [campusName, t]);

  const openLanguagePicker = useCallback(() => {
    setDraft(activeLang);
    setChoosing(true);
  }, [activeLang]);

  const confirmLanguage = useCallback((code: string) => {
    writeStorage("cc.lang", code);
    setSaved(code);
    setDraft(null);
    setChoosing(false);
  }, []);

  if (campus.notFound) return <NotFound />;
  if (!campus.loaded) return <Loading />;

  if (showWelcome) {
    if (offered.length && welcomeLang) {
      return (
        <Welcome
          churchName={churchName}
          languages={offered}
          selected={welcomeLang}
          onSelect={setDraft}
          onContinue={confirmLanguage}
        />
      );
    }
    return (
      <main className="flex min-h-[100dvh] flex-col items-center justify-center gap-6 px-6 text-2xl">
        <Logo churchName={churchName} size="lg" />
        <Message title={t("errors.retrying")}>
          <WaitingDots />
        </Message>
      </main>
    );
  }

  const lang = activeLang ?? "en";
  const sizeClass = TEXT_SIZE_CLASSES[textSize] ?? TEXT_SIZE_CLASSES[1];

  return (
    <div className="flex h-[100dvh] flex-col">
      <Header
        churchName={churchName}
        campusName={campusName}
        languageName={displayInfo?.name ?? lang}
        pill={pillFor(online, campus.failures, status, connection)}
        textSize={textSize}
        onTextSize={setTextSize}
        onChangeLanguage={openLanguagePicker}
      />
      <main className="flex min-h-0 flex-1 flex-col">
        <Body
          status={status}
          failures={campus.failures}
          offsetMs={campus.offsetMs}
          lang={lang}
          sizeClass={sizeClass}
          captions={captions}
        />
      </main>
    </div>
  );
}

interface BodyProps {
  status: CampusStatus | null;
  failures: number;
  offsetMs: number;
  lang: string;
  sizeClass: string;
  captions: ReturnType<typeof useCaptionStream>["captions"];
}

function Body({ status, failures, offsetMs, lang, sizeClass, captions }: BodyProps) {
  const { t } = useTranslation();
  const wrap = (node: ReactNode) => (
    <div className={`flex flex-1 items-center overflow-y-auto ${sizeClass}`}>{node}</div>
  );

  if (failures > 0 || !status || status.phase === "unavailable") {
    return wrap(
      <Message title={t("errors.retrying")}>
        <WaitingDots />
      </Message>,
    );
  }

  switch (status.phase) {
    case "upcoming":
      return wrap(
        status.next ? (
          <Countdown next={status.next} offsetMs={offsetMs} lang={lang} timeZone={status.timezone} />
        ) : (
          <Message title={t("schedule.idle")} />
        ),
      );
    case "ended":
      return wrap(
        <Message title={t("schedule.ended")}>
          {status.next && (
            <p className="text-gray-600">
              {t("schedule.nextServiceAt", { when: formatDateTime(status.next.start, lang, status.timezone) })}
            </p>
          )}
        </Message>,
      );
    case "idle":
      return wrap(<Message title={t("schedule.idle")} />);
    case "live":
      switch (status.captions) {
        case "live":
          return <Captions captions={captions} sizeClass={sizeClass} />;
        case "disconnected":
          return wrap(<Message title={t("captions.disconnected")} />);
        case "unavailable":
          return wrap(<Message title={t("captions.unavailable")} />);
        default:
          return wrap(
            <Message title={t("captions.waiting")}>
              <WaitingDots />
            </Message>,
          );
      }
  }
}
