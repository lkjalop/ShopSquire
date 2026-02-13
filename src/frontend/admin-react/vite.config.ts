import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = (env.VITE_API_BASE || env.VITE_API_BASE_URL || 'http://127.0.0.1:8081').replace(/\/+$/, '');

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
