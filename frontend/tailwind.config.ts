import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#eef7ff",
          100: "#d9edff",
          500: "#1f7ae0",
          600: "#1565c0",
          700: "#0f4c92",
        },
      },
      fontFamily: {
        sans: ["Vazirmatn", "Tahoma", "Arial", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;
