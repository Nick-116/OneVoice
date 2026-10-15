import { describe, expect, it } from "vitest";
import { locales } from "../i18n";

const PLURAL = /_(zero|one|two|few|many|other)$/;

function flatten(obj: unknown, prefix = ""): string[] {
  if (typeof obj !== "object" || obj === null) return [prefix];
  return Object.entries(obj).flatMap(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k));
}

const REQUIRED_PLURALS: Record<string, string[]> = {
  ar: ["zero", "one", "two", "few", "many", "other"],
  ru: ["one", "few", "many", "other"],
  uk: ["one", "few", "many", "other"],
  es: ["one", "many", "other"],
  pt: ["one", "many", "other"],
  fr: ["one", "many", "other"],
};

describe("locales", () => {
  const en = new Set(flatten(locales.en).map((k) => k.replace(PLURAL, "")));

  for (const [code, data] of Object.entries(locales)) {
    it(`${code} has the same keys as en`, () => {
      const keys = new Set(flatten(data).map((k) => k.replace(PLURAL, "")));
      expect([...keys].sort()).toEqual([...en].sort());
    });

    it(`${code} has the plural forms it needs`, () => {
      const keys = flatten(data);
      const forms = REQUIRED_PLURALS[code] ?? ["one", "other"];
      for (const form of forms) expect(keys).toContain(`schedule.startsInMinutes_${form}`);
    });
  }
});
