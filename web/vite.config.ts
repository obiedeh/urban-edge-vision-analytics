import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/api": "http://localhost:8080",
      "/cameras": "http://localhost:8080",
      "/events": "http://localhost:8080",
      "/incidents": "http://localhost:8080",
      "/metrics": "http://localhost:8080",
      "/use-cases": "http://localhost:8080",
      "/stream": "http://localhost:8080",
      "/artifacts": "http://localhost:8080",
      "/runtime": "http://localhost:8080",
      "/health": "http://localhost:8080",
      "/pipeline": "http://localhost:8080",
    },
  },
});
