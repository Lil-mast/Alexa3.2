import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The public app is at the Vercel root, so the base is "/". The operator
// console is a hash route (#/console/...) inside the same bundle. In
// production VITE_API_BASE points at the Render API; in development the proxy
// keeps the browser origin at 5173, which the backend already allows.
// Vite's root is the repository root: index.html and src/ sit beside backend/.
export default defineConfig({
  base: "/",
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
