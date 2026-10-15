import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Accent color chosen in the admin dashboard (Branding). Values are CSS variables set at
      // runtime from /api/public/config; defaults live in index.css. The server derives
      // 600/700/800 so text and white-on-accent buttons meet WCAG AA contrast.
      colors: {
        brand: Object.fromEntries(
          ["50", "100", "500", "600", "700", "800"].map((s) => [s, `rgb(var(--brand-${s}) / <alpha-value>)`]),
        ),
      },
      // Fonts are chosen in the admin dashboard (Branding) and applied via CSS variables;
      // --font-system (index.css) is the multilingual fallback stack.
      fontFamily: {
        sans: ["var(--font-body)"],
        name: ["var(--font-name)"],
      },
    },
  },
  plugins: [],
} satisfies Config;
