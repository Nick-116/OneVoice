// Self-hosted, open-license fonts (SIL OFL) bundled with the app: the strict CSP
// forbids third-party font CDNs. Browsers download only the font actually used,
// and only the character subsets needed. Scripts a font does not cover (CJK,
// Arabic, Devanagari...) fall back to the system stack automatically.
//
// Keep keys in sync with FONTS in backend/captions/branding.py.
import "@fontsource-variable/inter";
import "@fontsource-variable/open-sans";
import "@fontsource/lato/400.css";
import "@fontsource/lato/700.css";
import "@fontsource-variable/nunito";
import "@fontsource-variable/source-sans-3";
import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "@fontsource/merriweather/400.css";
import "@fontsource/merriweather/700.css";
import "@fontsource-variable/lora";
import "@fontsource-variable/playfair-display";
import "@fontsource-variable/montserrat";
import "@fontsource/poppins/400.css";
import "@fontsource/poppins/600.css";
import "@fontsource-variable/cinzel";
import "@fontsource/cormorant-garamond/500.css";
import "@fontsource/cormorant-garamond/700.css";
import "@fontsource-variable/raleway";

export const FONT_FAMILIES: Record<string, string> = {
  system: "",
  inter: "'Inter Variable'",
  "open-sans": "'Open Sans Variable'",
  lato: "'Lato'",
  nunito: "'Nunito Variable'",
  "source-sans": "'Source Sans 3 Variable'",
  atkinson: "'Atkinson Hyperlegible'",
  merriweather: "'Merriweather'",
  lora: "'Lora Variable'",
  playfair: "'Playfair Display Variable'",
  montserrat: "'Montserrat Variable'",
  poppins: "'Poppins'",
  cinzel: "'Cinzel Variable'",
  cormorant: "'Cormorant Garamond'",
  raleway: "'Raleway Variable'",
};

/** CSS font-family value for a font key: the chosen font first, then the system stack. */
export function fontStack(key: string | null | undefined): string {
  const family = (key && FONT_FAMILIES[key]) || "";
  return family ? `${family}, var(--font-system)` : "var(--font-system)";
}
