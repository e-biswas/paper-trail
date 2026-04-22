/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        bg: "hsl(var(--bg))",
        fg: "hsl(var(--fg))",
        muted: {
          DEFAULT: "hsl(var(--muted))",
          fg: "hsl(var(--muted-fg))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          fg: "hsl(var(--card-fg))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          fg: "hsl(var(--accent-fg))",
        },
        status: {
          pending: "hsl(var(--status-pending))",
          checking: "hsl(var(--status-checking))",
          confirmed: "hsl(var(--status-confirmed))",
          refuted: "hsl(var(--status-refuted))",
          verdict: "hsl(var(--status-verdict))",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        lg: "12px",
        md: "8px",
        sm: "6px",
      },
      animation: {
        "fade-in": "fade-in 200ms ease-out",
        "slide-up": "slide-up 220ms ease-out",
        "verdict-glow": "verdict-glow 2s ease-in-out",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "slide-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "verdict-glow": {
          "0%, 100%": { boxShadow: "0 0 0 rgba(251,191,36,0)" },
          "50%": { boxShadow: "0 0 18px rgba(251,191,36,0.6)" },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
}
