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
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Roboto",
          '"Noto Sans"',
          '"Helvetica Neue"',
          "Arial",
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          '"Noto Sans CJK SC"',
          '"Apple SD Gothic Neo"',
          '"Malgun Gothic"',
          '"Noto Sans KR"',
          '"Geeza Pro"',
          "Tahoma",
          '"Noto Sans Arabic"',
          '"Kohinoor Devanagari"',
          '"Nirmala UI"',
          '"Noto Sans Devanagari"',
          "sans-serif",
          '"Apple Color Emoji"',
          '"Segoe UI Emoji"',
        ],
      },
    },
  },
  plugins: [],
} satisfies Config;
