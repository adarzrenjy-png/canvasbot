import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, Vite serves the UI and forwards /api to the Python backend.
const backend = process.env.JIG_BACKEND_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { "/api": backend } },
  build: { chunkSizeWarningLimit: 1500 },
});
