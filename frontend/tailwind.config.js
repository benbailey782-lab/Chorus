/** @type {import('tailwindcss').Config} */
// Design tokens per CHORUS-SPEC §15.8. The legacy Phase-1 tokens (ink/parchment)
// were retired when Phase 2 landed; every component now targets the dark palette.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0A0A0B",
        surface: "#141416",
        "surface-2": "#1C1C21",
        border: "#2A2A2E",
        fg: "#FAFAFA",
        muted: "#9A9AA0",
        accent: {
          DEFAULT: "#4EC8BE",
          fg: "#062824", // readable text on top of accent swatches
        },
        warn: "#F59E0B",
        error: "#EF4444",
        success: "#10B981",
      },
      fontFamily: {
        display: ["'Playfair Display'", "Georgia", "serif"],
        body: ["'Inter'", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: {
        card: "0.75rem",
      },
      minHeight: {
        tap: "44px", // §15.2 minimum touch target
      },
      minWidth: {
        tap: "44px",
      },
    },
  },
  plugins: [],
};
