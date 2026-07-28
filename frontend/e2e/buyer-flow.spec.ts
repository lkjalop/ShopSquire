import { test, expect, Page } from '@playwright/test';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

// The dev key the browser bundle already ships with (VITE_API_KEY) — used to seed the cart deterministically
// over the API. Not a secret: it's inlined into the served JS.
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

/**
 * Direct clickthrough of the shopper storefront against the live dev stack (Vite :5173 + backend :8080
 * with the multi-intent planner enabled). Covers the browser-only checks: no internal ranker tags leak to
 * a buyer (T1), and the P0 multi-intent Confirm-qty path works end-to-end (T4) — the sourcing-backed
 * amendment that used to 409.
 *
 * Note on #3 (debug metadata): the badge is gated on `localStorage.shopsquire_debug === '1'` ONLY (the
 * DEV-build auto-enable was removed so the badge never leaks on the demo dev server). It is hidden here by
 * default, which is why T1's no-rank-tags-in-body check is a reliable buyer-facing invariant.
 */

async function openChatAndSend(page: Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  if (!(await input.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /Ask Me/i }).click();
    await input.waitFor({ state: 'visible' });
  }
  await input.click();
  await input.fill(text);
  await input.press('Enter');
}

test.describe('shopper storefront', () => {
  test('T1 — search shows products with no internal ranker tags leaked to the buyer', async ({ page }) => {
    await page.goto('/');
    await openChatAndSend(page, 'gaming laptop under 1500');
    await expect(page.getByText(/laptop/i).first()).toBeVisible({ timeout: 60_000 });
    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/\+in_stock|ram_gb_min|embedding_similarity|cross_encoder/);
  });

  const T4_UID = `e2e-t4-buyer-${Date.now()}`;
  const T4_SKU = 'LAP-0003';  // canonical, in-stock business laptop the amendment binds "__last__" to

  test('T4 — multi-intent Confirm-qty sets the laptop line to 15 (sourcing-backed, no 409)', async ({ page }) => {
    // This regression targets the canonical query response + confirmation UI.
    // Streaming parity is covered by voice-v2-pilot; abort SSE here so an
    // idempotent fallback cannot make this cart-mutation assertion model-timing dependent.
    await page.route('**/api/v1/chat/stream', (route) => route.abort());
    // 1) DURABLE prior selection: seed the cart over the API (the storefront's "in stock" pick can 409 on
    // add, and the Redis-shortlist fallback is a cross-turn race — a real cart line makes the amendment
    // deterministic, which is what a production test needs).
    await page.addInitScript((uid) => { try { sessionStorage.setItem('uid', uid); } catch { /* no-op */ } }, T4_UID);
    const key = devApiKey();
    expect(key, 'VITE_API_KEY must be readable from .env.local for the cart seed').not.toEqual('');
    const seed = await page.request.put(`/api/v1/cart/items/${T4_SKU}`, {
      headers: { 'x-api-key': key, 'Content-Type': 'application/json' },
      data: { uid: T4_UID, sku: T4_SKU, quantity: 1 },
    });
    expect(seed.ok(), `cart seed failed (${seed.status()})`).toBeTruthy();

    await page.goto('/');

    // 2) the mixed multi-intent turn — amend the cart laptop's qty + scope two new categories. (No "too
    // expensive" objection: with browser context that phrasing classifies as SUPPORT_CLAIM, which chat.py
    // deliberately skips the planner for — a support turn, not a cart-changing one. The amendment itself is
    // what T4 exercises.)
    const queryResponse = page.waitForResponse(
      (response) => response.url().includes('/api/v1/chat/query'),
      { timeout: 90_000 },
    );
    await openChatAndSend(page, 'actually make it 15, and get me headsets and hard drives for 1200 for those');
    const queryData = await (await queryResponse).json();
    expect(
      Array.isArray(queryData?.multi_intent?.plan) ? queryData.multi_intent.plan.length : 0,
      'canonical chat response must carry the governed mixed-intent plan',
    ).toBeGreaterThan(0);

    // 3) the confirmation card renders with the amendment + scoped picks
    const card = page.getByTestId('multi-intent-card');
    await expect(card).toBeVisible({ timeout: 60_000 });
    // target the amend ROW testid (the qty lives in a nested <strong>, so a /quantity to.*15/ text regex
    // races the card's internal render); assert the row's content instead.
    const amendRow = card.locator('[data-testid^="multi-intent-amend-"]');
    await expect(amendRow).toBeVisible({ timeout: 30_000 });
    await expect(amendRow).toContainText('15');

    // 4) confirm the qty → the guarded cart mutation succeeds and the
    // authoritative cart panel reflects the exact requested quantity.
    await card.getByRole('button', { name: 'Confirm qty' }).click();
    await expect(page.locator('[data-testid^="qty-"]').first()).toHaveText('15', { timeout: 30_000 });
  });
});
