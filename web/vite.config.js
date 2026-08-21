import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to FastAPI through a dev-server proxy, so the browser only
// ever sees same-origin requests. SSE needs buffering off to stream node by node.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
