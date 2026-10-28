import type { Config } from "tailwindcss";

// Tokens vêm de configs/ui/design-tokens.json espelhados em CSS variables (globals.css).
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)", surface: "var(--surface)", text: "var(--text)", muted: "var(--muted)", line: "var(--border)",
        accent: "var(--accent)", ok: "var(--ok)", warn: "var(--warn)", danger: "var(--danger)",
      },
      borderRadius: { btn: "10px", card: "14px", modal: "16px" },
      fontFamily: { sans: ["-apple-system", "BlinkMacSystemFont", "Inter", "Segoe UI", "sans-serif"] },
      maxWidth: { page: "1440px" },
      minHeight: { touch: "44px" },
    },
  },
  plugins: [],
};
export default config;
