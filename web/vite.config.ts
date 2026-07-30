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
    proxy: {
      "/api": "http://localhost:8080",
      "/cameras": "http://localhost:8080",
      "/events": "http://localhost:8080",
      "/incidents": "http://localhost:8080",
      "/inference": "http://localhost:8080",
      "/metrics": "http://localhost:8080",
      "/use-cases": "http://localhost:8080",
      "/stream": "http://localhost:8080",
      "/artifacts": "http://localhost:8080",
      "/runtime": "http://localhost:8080",
      "/health": "http://localhost:8080",
      "/pipeline": "http://localhost:8080",
      "/webrtc": "http://localhost:8080",
      "/live/results": "http://localhost:8080",
    },
  },
});
