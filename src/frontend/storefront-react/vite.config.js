import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      // Proxy backend so SSE/EventSource works same-origin (avoids CORS issues).
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true },
      '/ui': { target: 'http://127.0.0.1:8080', changeOrigin: true },
      '/static': { target: 'http://127.0.0.1:8080', changeOrigin: true },
      '/admin': { target: 'http://127.0.0.1:8080', changeOrigin: true },
    },
  },
});
