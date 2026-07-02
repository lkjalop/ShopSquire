import { defineConfig, devices } from '@playwright/test';

/**
 * E2E config for the shopper storefront. Assumes the dev stack is already running
 * (Vite :5173 + backend :8080 with MULTI_INTENT_PLANNER_ENABLED=1) — we don't spawn a webServer
 * because the demo servers are managed outside the test run. Headless by default; keep retries low
 * because the flows hit the real backend.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 150_000,
  expect: { timeout: 20_000 },
  retries: 1,
  reporter: [['line']],
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    actionTimeout: 20_000,
    trace: 'on',            // full Playwright trace (npx playwright show-trace ...) for every run
    video: 'on',            // record a .webm of every run → test-results/**/video.webm (screen-recordable proof)
    screenshot: 'on',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
