import { test, expect, Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

/**
 * Recorded PHASE-3 adaptive-storefront beat (video: on) — David's "detect a demand signal → re-emphasize
 * the storefront, GOVERNED and REVERSIBLE." Proves the whole loop end-to-end in the browser:
 *   1. a STRONG demand signal (confidence >= the calibrated floor) → the gate ALLOWS → the storefront
 *      re-ranks (sales_response_nudge boosts the in-demand, in-stock items);
 *   2. a WEAK signal (confidence < floor) → the gate DENIES (low_confidence) → NO adaptation (it does not
 *      act on noise — the calibrated confidence gate, off 0);
 *   3. clear the signal → the storefront REVERTS.
 * Every decision (allow + deny) is durably audited server-side. The signal is injected via the demo script
 * (a market_finding the live gate then judges) — nothing here sends or mutates customer-facing state.
 */

const here = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(here, '../..');

function devApiKey(): string {
  if (process.env.VITE_API_KEY?.trim()) return process.env.VITE_API_KEY.trim();
  for (const rel of ['../.env.local', '../.env.development.local']) {
    try {
      const m = readFileSync(resolve(here, rel), 'utf8').match(/^VITE_API_KEY=(.*)$/m);
      if (m && m[1].trim()) return m[1].trim();
    } catch { /* next */ }
  }
  return '';
}

// inject / clear the demand signal via the demo script (runs at the repo root so the module import resolves)
function seedDemand(args: string[]): void {
  execFileSync('poetry', ['run', 'python', '-m', 'scripts.demo_market_adaptation', ...args],
    { cwd: REPO, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, stdio: 'pipe' });
}

async function suggest(page: Page, query: string): Promise<any> {
  const r = await page.request.get(
    `/api/v1/recommend/suggest?query=${encodeURIComponent(query)}&uid=mkt-${Date.now()}&limit=8`,
    { headers: { 'x-api-key': devApiKey() } });
  expect(r.ok(), `suggest failed (${r.status()})`).toBeTruthy();
  return r.json();
}

test.beforeAll(() => { seedDemand(['--clear']); });
test.afterAll(() => { seedDemand(['--clear']); });

test('adaptive storefront — strong signal adapts, weak signal is governed, clearing reverts', async ({ page }) => {
  await test.step('1 · STRONG demand signal → the storefront re-ranks (gate ALLOWS)', async () => {
    seedDemand(['--direction', 'spike', '--confidence', '0.85', '--severity', 'critical']);
    // drive it in the browser so the recording shows the storefront; assert on the response it receives
    await page.goto('/');
    const input = page.getByPlaceholder('Type your message...');
    if (!(await input.isVisible().catch(() => false))) {
      await page.getByRole('button', { name: /Ask Me/i }).click();
      await input.waitFor({ state: 'visible' });
    }
    // TRANSPORT-AGNOSTIC: the app tries /chat/stream first and only falls back to /chat/query when the
    // stream is slow — waiting on /query alone flakes whenever the model is warm enough for the stream
    // to win. Drive the turn in the browser (for the recording), wait for EITHER chat transport to
    // complete, then assert the governed adaptation via the suggest API (same gate, deterministic).
    const chatResp = page.waitForResponse((r) => /\/api\/v1\/chat\/(query|stream)/.test(r.url()), { timeout: 60_000 });
    await input.fill('business laptop for the office');
    await input.press('Enter');
    await chatResp;
    const d = await suggest(page, 'business laptop for the office');
    const nudge = d?.sales_response_nudge;
    expect(nudge, 'suggest should carry the sales_response_nudge').toBeTruthy();
    expect(nudge.gate).toBe('allow');
    expect(nudge.applied).toBeGreaterThan(0);
    expect(nudge.demand_trend).toBe('rising');
    await page.waitForTimeout(3000);
  });

  await test.step('2 · WEAK signal → the gate DENIES (governed — does not act on noise)', async () => {
    seedDemand(['--direction', 'spike', '--confidence', '0.3', '--severity', 'warn']);
    const d = await suggest(page, 'business laptop for the office');
    expect(d.sales_response_nudge?.gate).toBe('low_confidence');
    expect(d.sales_response_nudge?.applied).toBe(0);
  });

  await test.step('3 · clear the signal → the storefront REVERTS (no adaptation)', async () => {
    seedDemand(['--clear']);
    const d = await suggest(page, 'business laptop for the office');
    // no active demand finding → nothing actionable → the nudge is absent/no-op
    expect(d.sales_response_nudge == null || d.sales_response_nudge.applied === 0).toBeTruthy();
  });
});
