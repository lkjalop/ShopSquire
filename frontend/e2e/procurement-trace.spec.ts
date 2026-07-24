import { test, expect, Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

/**
 * Recorded PROCUREMENT DECISION-TRACE beat (video: on) — the strongest investor moment on one screen:
 * the AI drafted a real supplier RFQ, routed it to the CORRECT supplier, human-gated (never sent), with a
 * full bitemporal audit — and it RE-ROUTES when the product changes.
 *
 * Deterministic: each case is seeded over the API and bound to a known trace_id, then opened via the
 * /?trace=<id>&tracetab=procurement deep-link. No LLM timing, no multi-step UI race.
 */

function envValue(name: string): string {
  const here = dirname(fileURLToPath(import.meta.url));
  for (const rel of ['../.env.local', '../.env.development.local']) {
    try {
      const m = readFileSync(resolve(here, rel), 'utf8').match(new RegExp(`^${name}=(.*)$`, 'm'));
      if (m && m[1].trim()) return m[1].trim();
    } catch { /* next */ }
  }
  return '';
}

async function seedDraftedCase(page: Page, { uid, trace, sku, qty }: { uid: string; trace: string; sku: string; qty: number }): Promise<void> {
  const key = envValue('VITE_API_KEY');
  expect(key, 'VITE_API_KEY must be readable from .env.local').not.toEqual('');
  const h = { 'x-api-key': key, 'Content-Type': 'application/json' };
  await page.request.put(`/api/v1/cart/items/${sku}`, { headers: h, data: { uid, sku, quantity: qty, allow_sourcing: true } });
  const cc = await page.request.post('/api/v1/fulfillment/cases/confirm-cart', {
    headers: h, data: { uid, order_id: `ord-${uid}`, trace_id: trace, lines: [{ item_ref: sku, requested_qty: qty }] },
  });
  expect(cc.ok(), `confirm-cart failed (${cc.status()})`).toBeTruthy();
  const cid = ((await cc.json()).cases || [])[0]?.case_id;
  expect(cid, 'no case created').toBeTruthy();
  // commit (GATE 1) → auto-drafts the supplier RFQ (case reaches QUOTE_DRAFTED)
  const commit = await page.request.post(`/api/v1/fulfillment/cases/${cid}/commit`, { headers: h, data: { uid } });
  expect(commit.ok(), `commit failed (${commit.status()})`).toBeTruthy();
}

test('procurement decision trace — drafted supplier RFQ + audit, re-routes per product', async ({ page }) => {
  // owner key → the operator drafted-RFQ drill-down is visible (a normal shopper never sees a supplier contact)
  await page.addInitScript((k) => { try { if (k) sessionStorage.setItem('ss_owner_key', k); } catch { /* no-op */ } }, envValue('VITE_OWNER_API_KEY'));
  // unique per run so each run seeds a FRESH case (a re-used uid/trace would 409 on the second commit)
  const run = String(Date.now());

  await test.step('1 · a bulk LAPTOP order → the AI drafts an RFQ to the business supplier (human-gated)', async () => {
    const trace = `inv-rec-laptop-${run}`;
    await seedDraftedCase(page, { uid: `inv-rec-laptop-${run}`, trace, sku: 'LAP-433AB371', qty: 25 });
    await page.goto(`/?trace=${trace}&tracetab=procurement`);

    await expect(page.getByTestId('proc-drafted-rfq')).toBeVisible({ timeout: 30_000 });
    // routed to the BUSINESS supplier, not a guess; only the shortfall is sourced
    await expect(page.getByTestId('proc-rfq-recipient')).toContainText('SUP-BIZ');
    await expect(page.getByTestId('proc-rfq-subject')).toContainText('LAP-433AB371');
    await expect(page.getByTestId('proc-rfq-body')).toContainText(/quote/i);
    await expect(page.getByTestId('proc-deal-economics')).toBeVisible();
    await expect(page.getByTestId('proc-deal-economics')).toContainText(/Operator-only/i);
    await expect(page.getByTestId('proc-discount-authorization')).toContainText(
      /locked until landed cost is validated|Authorized headroom/i,
    );
    // the bitemporal audit trail is right there — no window-hopping
    await expect(page.getByTestId('proc-audit-trail')).toBeVisible();
    await expect(page.getByTestId('proc-audit-trail')).toContainText(/QUOTE DRAFTED|COMMITTED/i);
    await page.waitForTimeout(3500); // let the recording breathe on the RFQ + audit
  });

  await test.step('2 · change the product to an SSD → the RFQ RE-ROUTES to a different supplier', async () => {
    const trace = `inv-rec-ssd-${run}`;
    await seedDraftedCase(page, { uid: `inv-rec-ssd-${run}`, trace, sku: 'HDD-30C9A5E1', qty: 30 });
    await page.goto(`/?trace=${trace}&tracetab=procurement`);

    await expect(page.getByTestId('proc-drafted-rfq')).toBeVisible({ timeout: 30_000 });
    // a different product → a different approved supplier + a different RFQ (proves it's product-derived)
    await expect(page.getByTestId('proc-rfq-recipient')).toContainText('SUP-OFFICE');
    await expect(page.getByTestId('proc-rfq-subject')).toContainText('HDD-30C9A5E1');
    await expect(page.getByTestId('proc-rfq-recipient')).not.toContainText('SUP-BIZ');
    await page.waitForTimeout(3500);
  });
});
