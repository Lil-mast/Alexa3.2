import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The console is served at /console both in dev and in production, so asset
// paths and the hash route never differ between the two. The proxy keeps the
// browser origin at 5173, which is the origin the backend already allows.
export default defineConfig({
  base: "/console/",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
      "/health": { target: "http://localhost:8000", changeOrigin: false },
      // The API docs link in the footer is proxied too, so it works in dev.
      "/docs": { target: "http://localhost:8000", changeOrigin: false },
      "/openapi.json": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
