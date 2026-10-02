import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import fs from "node:fs";

const https =
  process.env.VITE_DEV_HTTPS_KEY && process.env.VITE_DEV_HTTPS_CERT
    ? {
        key: fs.readFileSync(process.env.VITE_DEV_HTTPS_KEY),
        cert: fs.readFileSync(process.env.VITE_DEV_HTTPS_CERT),
      }
    : undefined;

// Dev-only proxy target for the FastAPI backend (production serves web/dist from uvicorn itself).
// Override with e.g. `VITE_DEV_API_TARGET=http://localhost:18090 pnpm dev`.
const apiTarget = process.env.VITE_DEV_API_TARGET ?? "http://localhost:8080";

const apiPrefixes = [
  "/cameras",
  "/use-cases",
  "/stream",
  "/live",
  "/webrtc",
  "/settings",
  "/runtime",
  "/host",
  "/inference",
  "/events",
  "/incidents",
  "/metrics",
  "/artifacts",
  "/health",
];

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  server: {
    https,
    port: 3000,
    proxy: Object.fromEntries(
      apiPrefixes.map((p) => [
        p,
        {
          target: apiTarget,
          changeOrigin: true,
          // SPA routes share these prefixes (/live, /events, /cameras ...): only proxy
          // requests that are not asking for an HTML document.
          bypass: (req: { headers: Record<string, string | string[] | undefined> }) => {
            const accept = req.headers.accept;
            const a = Array.isArray(accept) ? accept.join(",") : accept ?? "";
            if (a.includes("text/html") && !a.includes("multipart/x-mixed-replace")) return "/index.html";
            return undefined;
          },
        },
      ])
    ),
  },
});
