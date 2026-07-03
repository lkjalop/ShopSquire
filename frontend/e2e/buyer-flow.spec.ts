import { test, expect, Page } from '@playwright/test';

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

  test('T4 — multi-intent Confirm-qty sets the laptop line to 15 (sourcing-backed, no 409)', async ({ page }) => {
    await page.goto('/');
    // 1) establish a prior selection — search laptops (populates the shortlist the planner falls back to)
    await openChatAndSend(page, 'business laptop around 1300');
    await expect(page.getByText(/laptop/i).first()).toBeVisible({ timeout: 60_000 });
    // Let the first turn FULLY settle so its shortlist is persisted to Redis before the amendment turn reads
    // it (the planner falls back to that shortlist when the cart is empty). The main flake source was this
    // race + a cross-<strong> text regex below; a longer settle + a testid-anchored assertion remove both.
    await page.waitForTimeout(4000);

    // 2) the mixed multi-intent turn
    await openChatAndSend(page, 'nah too expensive, actually i need 15 instead. what headsets and hard drives for 1200 for those?');

    // 3) the confirmation card renders with the amendment + scoped picks
    const card = page.getByTestId('multi-intent-card');
    await expect(card).toBeVisible({ timeout: 60_000 });
    // target the amend ROW testid (the qty lives in a nested <strong>, so a /quantity to.*15/ text regex
    // races the card's internal render); assert the row's content instead.
    const amendRow = card.locator('[data-testid^="multi-intent-amend-"]');
    await expect(amendRow).toBeVisible({ timeout: 30_000 });
    await expect(amendRow).toContainText('15');

    // 4) confirm the qty → the sourcing-backed set succeeds (message names the sourced shortfall)
    await card.getByRole('button', { name: 'Confirm qty' }).click();
    await expect(page.getByText(/will be sourced|Set .* to 15/i)).toBeVisible({ timeout: 30_000 });
  });
});
