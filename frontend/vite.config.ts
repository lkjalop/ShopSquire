import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Default to docker-compose API port (8080).
  // Use `localhost` (not `127.0.0.1`) to avoid Windows loopback quirks with Docker/WSL port forwarding.
  // When running uvicorn locally, set `VITE_API_BASE_URL=http://localhost:8081`.
  const apiTarget = (env.VITE_API_BASE_URL || 'http://localhost:8080').replace(/\/+$/, '');

  return {
    plugins: [react()],
    server: {
      // Bind explicitly to IPv4 so `http://127.0.0.1:5173` works on Windows.
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/health': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/healthz': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/ui': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/static': {
          target: apiTarget,
          changeOrigin: true,
        }
      }
    }
  };
});
