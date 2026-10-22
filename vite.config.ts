import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The console is served at /console both in dev and in production, so asset
// paths and the hash route never differ between the two. The proxy keeps the
// browser origin at 5173, which is the origin the backend already allows.
// Vite's root is the repository root: index.html and src/ sit beside backend/.
export default defineConfig({
  base: "/console/",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // The Vite root is the repository root, so keep the Python tree out of the
    // watcher. Without this, a backend edit or a test run can trigger a reload.
    watch: {
      ignored: ["**/backend/**", "**/docs/**", "**/scripts/**", "**/.git/**"],
    },
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
