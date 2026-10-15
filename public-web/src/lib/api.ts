import { isCampusStatus, isPublicConfig } from "./guards";
import type { CampusStatus, PublicConfig } from "./types";

export type StatusResult =
  | { kind: "ok"; status: CampusStatus }
  | { kind: "notfound" }
  | { kind: "unavailable"; status: CampusStatus | null; retryAfterMs: number };

const INIT: RequestInit = {
  method: "GET",
  cache: "no-store",
  credentials: "omit",
  headers: { Accept: "application/json" },
};

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return undefined;
  }
}

function retryAfter(res: Response): number {
  const v = Number(res.headers.get("Retry-After"));
  return Number.isFinite(v) && v > 0 ? v * 1000 : 0;
}

export async function fetchConfig(signal?: AbortSignal): Promise<PublicConfig> {
  const res = await fetch("/api/public/config", { ...INIT, signal });
  if (!res.ok) throw new Error(`config ${res.status}`);
  const body = await readJson(res);
  if (!isPublicConfig(body)) throw new Error("config: bad payload");
  return {
    church_name: typeof body.church_name === "string" ? body.church_name : "",
    campuses: body.campuses,
    theme: body.theme && typeof body.theme === "object" ? body.theme : null,
    logo_version: typeof body.logo_version === "string" ? body.logo_version : null,
  };
}

export async function fetchStatus(slug: string, signal?: AbortSignal): Promise<StatusResult> {
  const res = await fetch(`/api/public/campus/${encodeURIComponent(slug)}`, { ...INIT, signal });
  if (res.status === 404) return { kind: "notfound" };
  const body = await readJson(res);
  if (res.ok && isCampusStatus(body) && body.phase !== "unavailable") return { kind: "ok", status: body };
  return { kind: "unavailable", status: isCampusStatus(body) ? body : null, retryAfterMs: retryAfter(res) };
}

export function streamUrl(slug: string, lang: string): string {
  return `/api/public/campus/${encodeURIComponent(slug)}/stream?lang=${encodeURIComponent(lang)}`;
}
