import type { Config } from "tailwindcss";

/**
 * دانشیار — Design tokens
 * Direction: light canvas + dark indigo sidebar, refined indigo/violet primary.
 * Semantic tokens: canvas (bg) · surface · line (border) · ink (text/muted)
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Primary — refined indigo
        primary: {
          50: "#eef1ff",
          100: "#e0e5ff",
          200: "#c6ccff",
          300: "#a3abfc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#2c2a7e",
          950: "#19184d",
        },
        // Accent — violet, for gradients & highlights
        accent: {
          50: "#f5f3ff",
          100: "#ede9fe",
          200: "#ddd6fe",
          300: "#c4b5fd",
          400: "#a78bfa",
          500: "#8b5cf6",
          600: "#7c3aed",
          700: "#6d28d9",
        },
        // Semantic surfaces
        canvas: "#f4f6fb",
        surface: {
          DEFAULT: "#ffffff",
          sunken: "#f8fafd",
        },
        line: {
          DEFAULT: "#e5e8f2",
          soft: "#eef1f8",
        },
        // Semantic text
        ink: {
          DEFAULT: "#101828",
          muted: "#5a6478",
          faint: "#98a1b3",
        },
        // Status scales
        success: {
          50: "#ecfdf3",
          100: "#d1fadf",
          500: "#12b76a",
          600: "#039855",
          700: "#027a48",
        },
        warning: {
          50: "#fffaeb",
          100: "#fef0c7",
          500: "#f79009",
          600: "#dc6803",
          700: "#b54708",
        },
        danger: {
          50: "#fef3f2",
          100: "#fee4e2",
          500: "#f04438",
          600: "#d92d20",
          700: "#b42318",
        },
      },
      fontFamily: {
        sans: ["var(--font-vazirmatn)", "Vazirmatn", "IRANSans", "Tahoma", "Arial", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(16,24,40,.04), 0 10px 26px -18px rgba(16,24,40,.22)",
        card: "0 1px 3px rgba(16,24,40,.05), 0 16px 40px -26px rgba(16,24,40,.30)",
        lift: "0 10px 34px -14px rgba(79,70,229,.45)",
        ring: "0 0 0 4px rgba(99,102,241,.16)",
        sidebar: "0 0 40px -18px rgba(0,0,0,.6)",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #6366f1 0%, #8b5cf6 55%, #a855f7 100%)",
        "brand-gradient-soft": "linear-gradient(135deg, rgba(99,102,241,.12) 0%, rgba(168,85,247,.12) 100%)",
        "sidebar-gradient": "linear-gradient(180deg, #10142e 0%, #171d3f 55%, #1c1743 100%)",
        "hero-gradient": "radial-gradient(1200px 600px at 85% -10%, rgba(129,140,248,.35), transparent 60%), radial-gradient(900px 500px at 10% 110%, rgba(168,85,247,.28), transparent 55%)",
      },
      borderRadius: {
        "4xl": "2rem",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
        "fade-in-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "grow-bar": {
          "0%": { transform: "scaleY(0)" },
          "100%": { transform: "scaleY(1)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s linear infinite",
        "fade-in-up": "fade-in-up .35s ease-out both",
        "fade-in": "fade-in .2s ease-out both",
        "grow-bar": "grow-bar .6s cubic-bezier(.22,1,.36,1) both",
      },
    },
  },
  plugins: [],
};
export default config;
