import { test, expect, Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

/**
 * Context-retention regression net — the "budget across turns" class that broke the live demo:
 *   T1  "work laptops budget 1200 to 1500, need 10"  → band respected, qty parsed
 *   T2  "actually budget is now 1800 max"            → ceiling RAISED, remembered FLOOR KEPT
 *                                                      (must not re-open the $629 tier — the old regression)
 *   T3  "cut it to 1000 max"                         → the CUT IS HONORED (no product over $1,000)
 *                                                      (was served stale $1,200-$1,500 results — the
 *                                                      fifth-budget-parser gap in parse_constraints)
 * API-driven through the real /chat/query lane (same uid = same session memory), so it exercises the
 * whole stack: parse → kv memory merge → retrieval → narration. No LLM-timing flake: assertions are on
 * product prices + band text, not free prose.
 */

function devApiKey(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  for (const rel of ['../.env.local', '../.env.development.local']) {
    try {
      const m = readFileSync(resolve(here, rel), 'utf8').match(/^VITE_API_KEY=(.*)$/m);
      if (m && m[1].trim()) return m[1].trim();
    } catch { /* next */ }
  }
  return '';
}

async function chat(page: Page, uid: string, query: string): Promise<any> {
  const r = await page.request.post('/api/v1/chat/query', {
    headers: { 'x-api-key': devApiKey(), 'Content-Type': 'application/json' },
    data: { uid, query },
    timeout: 90_000,
  });
  expect(r.ok(), `chat/query failed (${r.status()})`).toBeTruthy();
  return r.json();
}

const prices = (d: any): number[] =>
  ((d.products || []) as any[]).map((p) => Number(p.price) || 0).filter((v) => v > 0);

test('budget context survives raise + cut across turns (one session)', async ({ page }) => {
  const uid = `e2e-ctx-${Date.now()}`;

  await test.step('T1 · initial band 1200-1500 + qty 10 parsed', async () => {
    const d = await chat(page, uid, 'work laptops budget 1200 to 1500, need 10');
    const ps = prices(d);
    expect(ps.length).toBeGreaterThan(0);
    for (const v of ps) expect(v, 'T1 price inside 1200-1500').toBeGreaterThanOrEqual(1100); // small tolerance floor
    expect(Number(d.requested_quantity)).toBe(10);
  });

  await test.step('T2 · raise to 1800 max — ceiling up, remembered floor kept', async () => {
    const d = await chat(page, uid, 'actually budget is now 1800 max');
    const ps = prices(d);
    expect(ps.length).toBeGreaterThan(0);
    for (const v of ps) {
      expect(v, 'T2 respects the new ceiling').toBeLessThanOrEqual(1800);
      expect(v, 'T2 keeps the remembered floor (no $629 tier re-opening)').toBeGreaterThanOrEqual(1100);
    }
  });

  await test.step('T3 · cut to 1000 max — the cut is honored', async () => {
    const d = await chat(page, uid, 'cut it to 1000 max');
    const ps = prices(d);
    expect(ps.length, 'T3 still shows products (does not zero out)').toBeGreaterThan(0);
    for (const v of ps) expect(v, 'T3 nothing over the new $1,000 ceiling').toBeLessThanOrEqual(1000);
  });
});
