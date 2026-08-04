/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Default to docker-compose API (8080). Use `localhost` to avoid Windows loopback quirks.
  // When running uvicorn locally with defaults, set `VITE_API_BASE_URL=http://localhost:8080`.
  const apiTarget = (env.VITE_API_BASE || env.VITE_API_BASE_URL || 'http://localhost:8080').replace(/\/+$/, '');

  return {
    plugins: [react()],
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return undefined;
            if (id.includes('react') || id.includes('scheduler')) return 'react-vendor';
            return 'vendor';
          },
        },
      },
    },
    server: {
      port: 3001,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
        '/static': { target: apiTarget, changeOrigin: true },
        '/admin': { target: apiTarget, changeOrigin: true },
      },
    },
    // Component-test harness (vitest + jsdom). Coverage is left off here because
    // @vitest/coverage-v8 is not installed in this package; add it to enable `--coverage`.
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.{test,spec}.{ts,tsx}'],
    },
  };
});
