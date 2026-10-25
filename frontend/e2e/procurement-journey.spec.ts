import { test, expect, Page } from '@playwright/test';
import { registerBuyer } from './helpers/registeredBuyer';


async function send(page: Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  if (!(await input.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /Ask Me/i }).click();
  }
  await input.fill(text);
  await input.press('Enter');
}

test('demo procurement journey: clear, exact cart line, amendment and delivery reconfirmation', async ({ page }) => {
  test.setTimeout(180_000);
  const uid = await registerBuyer(page.context());
  await page.goto('/');

  await send(page, 'clear my cart');
  await expect(page.getByText(/cart is (?:already )?empty|cleared your cart|cart has been cleared/i).last())
    .toBeVisible({ timeout: 30_000 });

  const seeded = await page.request.post('/api/v1/cart/items', {
    data: { uid, sku: 'RGAM-0007', quantity: 10 },
  });
  expect(seeded.ok(), await seeded.text()).toBeTruthy();

  await send(page, 'increase the total units by another 5');
  const apply = page.getByRole('button', { name: /Apply change|Confirm.*apply to cart/i });
  await expect(apply).toBeVisible({ timeout: 75_000 });
  await apply.click();
  const quantity = page.locator('[data-testid^="qty-"]').first();
  await expect(quantity).toHaveText('15');
  await expect(page.locator('[data-testid^="qty-"]')).toHaveCount(1);
  await expect(page.getByText(
    /review and (?:re)?confirm the (?:revised|updated) delivery plan/i,
  ).last()).toBeVisible();
  await expect(page.getByText(/RFQ.*sent/i)).toHaveCount(0);
});
