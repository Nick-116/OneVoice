import { useCallback, useEffect, useState } from "react";
import { CampusPage } from "./components/CampusPage";
import { Home } from "./components/Home";
import { NotFound } from "./components/NotFound";

const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;

/** Campus pages live at /campus/<slug> (canonical, used by QR codes); /<slug> still works. */
export function slugFromPath(path: string): string | null | undefined {
  let parts = path.split("/").filter(Boolean);
  if (parts.length === 0) return null;
  if (parts[0] === "campus") {
    if (parts.length !== 2) return parts.length === 1 ? null : undefined;
    parts = parts.slice(1);
  }
  if (parts.length > 1) return undefined;
  let slug: string;
  try {
    slug = decodeURIComponent(parts[0] ?? "");
  } catch {
    return undefined;
  }
  return SLUG_RE.test(slug) ? slug : undefined;
}

export function App() {
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const goToCampus = useCallback((slug: string) => {
    const next = `/campus/${encodeURIComponent(slug)}`;
    window.history.replaceState(null, "", next);
    setPath(next);
  }, []);

  const slug = slugFromPath(path);
  if (slug === null) return <Home onSingleCampus={goToCampus} />;
  if (slug === undefined) return <NotFound />;
  return <CampusPage key={slug} slug={slug} />;
}
