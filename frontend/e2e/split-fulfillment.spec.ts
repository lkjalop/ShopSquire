import { test, expect, Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

/**
 * Recorded pre-payment split-fulfilment beat (video: on). A bulk laptop order exceeds on-hand stock, so
 * ShopSquire does NOT silently backorder — it shows the buyer, BEFORE payment, exactly what ships now (from
 * stock) and what follows from a supplier (with the SUPPLIER's real lead time as the ETA) plus the store's
 * delivery terms, and gates checkout on the buyer CONFIRMING that plan.
 *
 * The splitting cart is seeded deterministically over the API (allow_sourcing lets the qty exceed stock —
 * the same path the multi-intent "make it 25" confirm uses) so the recording is stable; the split card,
 * ETA, delivery terms, and the checkout gate are all exercised through the real UI.
 */

// The dev API key the browser bundle already ships with (VITE_API_KEY) — read from .env.local so the
// API-seed uses the same auth the app does. Not a secret: it's inlined into the served JS.
function devApiKey(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  for (const rel of ['../.env.local', '../.env.development.local']) {
    try {
      const txt = readFileSync(resolve(here, rel), 'utf8');
      const m = txt.match(/^VITE_API_KEY=(.*)$/m);
      if (m && m[1].trim()) return m[1].trim();
    } catch { /* try the next file */ }
  }
  return '';
}

const UID = 'e2e-split-buyer';
const SKU = 'LAP-0003';       // canonical seeded business laptop
const QTY = 100;              // deliberately exceeds aggregate seeded location stock

async function seedSplittingCart(page: Page) {
  const key = devApiKey();
  expect(key, 'VITE_API_KEY must be readable from .env.local for the API seed').not.toEqual('');
  const res = await page.request.put(`/api/v1/cart/items/${SKU}`, {
    headers: { 'x-api-key': key, 'Content-Type': 'application/json' },
    data: { uid: UID, sku: SKU, quantity: QTY, allow_sourcing: true },
  });
  expect(res.ok(), `seed PUT failed (${res.status()})`).toBeTruthy();
}

test('pre-payment split-fulfilment — ships now + supplier-ETA follow-up, buyer confirms before checkout', async ({ page }) => {
  await page.addInitScript((uid) => { try { sessionStorage.setItem('uid', uid); } catch { /* no-op */ } }, UID);

  await test.step('0 · a bulk order exceeds stock (seeded over the API, allow_sourcing)', async () => {
    await seedSplittingCart(page);
  });

  await test.step('1 · buyer opens the cart — the split plan is disclosed before payment', async () => {
    await page.goto('/');
    await page.getByRole('button', { name: /^Cart \(/ }).click();
    const card = page.getByTestId('split-fulfillment-card');
    await expect(card).toBeVisible({ timeout: 30_000 });
    // plain-English rationale that names the supplier-lead-time ETA
    await expect(page.getByTestId('split-rationale')).toContainText(
      /(?:follow in|supplier RFQ in) ~\d+ days \(supplier lead time\)/i,
    );
    // the backordered line carries the SUPPLIER's real ETA (a real figure, not a guess)
    await expect(page.getByTestId(`split-eta-${SKU}`)).toContainText(/~\d+ days/);
    // the store's delivery economics are shown (free over threshold, or per-shipment fees)
    await expect(page.getByTestId('split-delivery')).toContainText(/delivery/i);
    await page.waitForTimeout(2500);
  });

  await test.step('2 · checkout is GATED until the buyer confirms the delivery plan', async () => {
    const helper = page.getByTestId('cart-confirm-plan-first');
    await helper.scrollIntoViewIfNeeded();
    await expect(helper).toBeVisible();
    await expect(helper).toContainText(/Confirm delivery plan first/i);
    await helper.click();
    await expect(page.getByTestId('split-confirm')).toBeVisible();
    await page.waitForTimeout(1500);
  });

  await test.step('3 · buyer confirms the plan → checkout unlocks', async () => {
    await page.getByTestId('split-confirm').click();
    await expect(page.getByTestId('split-confirmed')).toBeVisible();
    await expect(page.getByTestId('cart-proceed')).toContainText(/Continue to checkout/i);
    await page.waitForTimeout(2500);
  });
});
