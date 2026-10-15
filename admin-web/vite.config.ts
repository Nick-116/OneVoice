/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Strict CSP (script-src 'self'; style-src 'self'): no inline scripts or styles in the
// generated index.html, and no data: URIs for anything except images.
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    assetsInlineLimit: 0,
    modulePreload: { polyfill: false },
    sourcemap: false,
    target: 'es2022',
  },
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://localhost:8081', changeOrigin: false },
    },
  },
  preview: { port: 5174 },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
