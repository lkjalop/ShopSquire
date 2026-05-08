import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = (env.VITE_API_BASE_URL || 'http://localhost:8080').replace(/\/+$/, '');
  const apiWsTarget = apiTarget.replace(/^http/, 'ws');

  return {
    plugins: [react()],
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'lcov'],
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/test/**', 'src/**/*.d.ts'],
      },
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true, ws: true },
        '/health': { target: apiTarget, changeOrigin: true },
        '/healthz': { target: apiTarget, changeOrigin: true },
        '/ui': { target: apiTarget, changeOrigin: true },
        '/static': { target: apiTarget, changeOrigin: true },
      },
      // CRIT-07: Security headers for the Vite dev server (port 5173).
      // Production builds are served behind nginx/CDN which must mirror these.
      headers: {
        'X-Frame-Options': 'DENY',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
        // Dev CSP — unsafe-eval needed for Vite HMR; report-only so it doesn't
        // break hot-reload while developers fix inline script usages.
        'Content-Security-Policy-Report-Only': [
          "default-src 'self'",
          "script-src 'self' 'unsafe-eval'",   // Vite HMR requires unsafe-eval in dev
          "style-src 'self' 'unsafe-inline'",
          "img-src 'self' data: blob: https:",
          `connect-src 'self' ${apiTarget} ${apiWsTarget} ws://localhost:5173`,
          "media-src 'self' blob:",
          "worker-src blob:",
          "object-src 'none'",
          "base-uri 'self'",
          "frame-ancestors 'none'",
          `report-uri ${apiTarget}/api/v1/security/csp-report`,
        ].join('; '),
      },
    }
  };
});
