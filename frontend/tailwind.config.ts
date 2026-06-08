import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        awsOrange: "#FF9900",
        awsSquidInk: "#232F3E",
        awsDarkNavy: "#F3F4F6",
        awsDeepBlue: "#E9EEF5",
        awsPanel: "#FFFFFF",
        awsPanelSoft: "#F8FAFC",
        awsBorder: "#D5DBDB",
        awsTextPrimary: "#111827",
        awsTextSecondary: "#374151",
        awsTextMuted: "#6B7280",
        awsSuccess: "#1E8E3E",
        awsWarning: "#F59E0B",
        awsDanger: "#DC2626",
        awsInfo: "#2563EB",
        background: "#F6F7F9",
        surface: "#FFFFFF",
        surfaceElevated: "#F8FAFC"
      },
      boxShadow: {
        console: "0 12px 28px rgba(15, 23, 42, 0.08)"
      }
    }
  },
  plugins: []
} satisfies Config;
