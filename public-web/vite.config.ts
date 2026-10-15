import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    assetsDir: "assets",
    // Never inline assets as data: URIs (fonts would be blocked by the CSP's font-src 'self').
    assetsInlineLimit: 0,
    emptyOutDir: true,
    sourcemap: false,
    target: "es2020",
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://localhost:8080", changeOrigin: true },
      "/branding": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
