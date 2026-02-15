import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Default to docker-compose API (8080). Use `localhost` to avoid Windows loopback quirks.
  // When running uvicorn locally, set `VITE_API_BASE_URL=http://localhost:8081`.
  const apiTarget = (env.VITE_API_BASE || env.VITE_API_BASE_URL || 'http://localhost:8080').replace(/\/+$/, '');

  return {
    plugins: [react()],
    server: {
      port: 3001,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
        '/static': { target: apiTarget, changeOrigin: true },
        '/admin': { target: apiTarget, changeOrigin: true },
      },
    },
  };
});
