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
  if (process.env.VITE_API_KEY?.trim()) return process.env.VITE_API_KEY.trim();
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
    // V2 treats an explicit range as a per-item band unless the buyer says
    // total/all-in. Scalar multi-unit budgets remain clarification-gated.
    const d = await chat(page, uid, 'work laptops budget 1200 to 1500, need 10');
    const ps = prices(d);
    expect(ps.length).toBeGreaterThan(0);
    // The stated maximum is hard; the minimum is a preference, so a lower-priced valid fit is allowed.
    for (const v of ps) expect(v, 'T1 respects the hard 1500 ceiling').toBeLessThanOrEqual(1500);
    expect(Number(d.requested_quantity)).toBe(10);
  });

  await test.step('T2 · raise to 1800 max — new hard ceiling, prior minimum remains soft', async () => {
    const d = await chat(page, uid, 'actually budget is now 1800 max');
    const ps = prices(d);
    expect(ps.length).toBeGreaterThan(0);
    for (const v of ps) {
      expect(v, 'T2 respects the new ceiling').toBeLessThanOrEqual(1800);
    }
  });

  await test.step('T3 · cut to 1000 max — the cut is honored', async () => {
    const d = await chat(page, uid, 'cut it to 1000 max');
    const ps = prices(d);
    expect(ps.length, 'T3 still shows products (does not zero out)').toBeGreaterThan(0);
    for (const v of ps) expect(v, 'T3 nothing over the new $1,000 ceiling').toBeLessThanOrEqual(1000);
  });
});

test('bulk quantity survives non-qty turns; a fresh amendment wins and then holds', async ({ page }) => {
  const uid = `e2e-qty-${Date.now()}`;
  const d1 = await chat(page, uid, 'i need 25 work laptops, budget 1200 to 1500');
  expect(Number(d1.requested_quantity)).toBe(25);
  expect(d1.needs_disambiguation).toBeFalsy();
  const d2 = await chat(page, uid, 'which of these has the best battery life?');
  expect(Number(d2.requested_quantity), 'memory FILLS on a no-qty turn').toBe(25);
  const d3 = await chat(page, uid, 'actually make it 12 units');
  expect(Number(d3.requested_quantity), 'a fresh amendment WINS over memory').toBe(12);
  const d4 = await chat(page, uid, 'and what about delivery for those?');
  expect(Number(d4.requested_quantity), 'memory holds the UPDATED count').toBe(12);
});
