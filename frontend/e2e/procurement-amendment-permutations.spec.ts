import { test, expect, Page } from '@playwright/test';

const API_KEY = process.env.VITE_API_KEY?.trim() || 'local-merchant-key';

async function send(page: Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  if (!(await input.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /Ask Me/i }).click();
  }
  const response = page.waitForResponse(
    (r) => /\/api\/v1\/chat\/(query|stream)/.test(r.url()),
    { timeout: 60_000 },
  );
  await input.fill(text);
  await input.press('Enter');
  await response;
}

test('relative bulk amendment preserves the cart line and exposes one confirmation authority', async ({ page }) => {
  const uid = `e2e-relative-amend-${Date.now()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  const seeded = await page.request.post('/api/v1/cart/items', {
    headers: { 'x-api-key': API_KEY },
    data: { uid, sku: 'RGAM-0007', quantity: 20 },
  });
  expect(seeded.ok(), await seeded.text()).toBeTruthy();

  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  await page.getByRole('button', { name: /Cart/i }).first().click().catch(() => undefined);

  await send(page, 'can you increase the total units by another 20?');

  const confirm = page.getByRole('button', { name: /Confirm.*apply to cart/i });
  await expect(confirm).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('multi-intent-card')).toHaveCount(0);
  await confirm.click();

  await expect(page.locator('[data-testid^="qty-"]').first()).toHaveText('40', { timeout: 30_000 });
  await expect(page.getByText(/Done.*applied the change to your cart/i).last()).toBeVisible();
  await expect(page.getByTestId('split-confirm')).toBeVisible();
  await expect(page.getByText(/Found \d+ products/i)).toHaveCount(0);
});

test('read-only procurement summary preserves the exact product panel', async ({ page }) => {
  const uid = `e2e-status-preserve-${Date.now()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await send(page, 'We need 18 RGAM-0007 laptops for a design studio, AUD 85000 total');
  await expect(page.getByText(/Found 1 product/i)).toBeVisible({ timeout: 40_000 });
  await expect(page.getByText(/HP OMEN MAX 16/i).first()).toBeVisible();

  await send(page, 'summarise this procurement case without changing it');

  await expect(page.getByText(/procurement case is still active for RGAM-0007.*18 units/i).last())
    .toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Found 1 product/i)).toBeVisible();
  await expect(page.getByText(/HP OMEN MAX 16/i).first()).toBeVisible();
});
