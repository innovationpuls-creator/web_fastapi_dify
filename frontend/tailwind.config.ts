import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#020304",
        mist: "#d9e4ff",
        pulse: "#94adff",
      },
      fontFamily: {
        sans: [
          "\"SF Pro Display\"",
          "\"Segoe UI Variable Text\"",
          "\"PingFang SC\"",
          "\"Hiragino Sans GB\"",
          "\"Microsoft YaHei\"",
          "sans-serif",
        ],
        mono: [
          "\"SF Mono\"",
          "\"JetBrains Mono\"",
          "\"Cascadia Code\"",
          "\"Roboto Mono\"",
          "monospace",
        ],
      },
      boxShadow: {
        aura: "0 0 40px rgba(148, 173, 255, 0.15)",
        ember: "0 0 32px rgba(255, 92, 123, 0.18)",
      },
      animation: {
        breathe: "breathe 2.8s ease-in-out infinite",
        "soft-pulse": "softPulse 1.8s ease-out infinite",
      },
      keyframes: {
        breathe: {
          "0%, 100%": { opacity: "0.12" },
          "50%": { opacity: "0.34" },
        },
        softPulse: {
          "0%": { opacity: "0.12", transform: "scale(0.98)" },
          "50%": { opacity: "0.3", transform: "scale(1.02)" },
          "100%": { opacity: "0.12", transform: "scale(0.98)" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
