import { test, expect } from '@playwright/test';

test('unfamiliar capability request clarifies before catalog, ATP or sourcing', async ({ page }) => {
  const uid = `e2e-semantic-${Date.now()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const input = page.getByPlaceholder('Type your message...');
  await input.fill('Please recommend a laptop for simulating a digital twin for maintenance of mechanical machines.');
  const started = Date.now();
  await input.press('Enter');

  await expect(page.getByTestId('stream-acknowledgement')).toBeVisible({ timeout: 1_500 });
  expect(Date.now() - started).toBeLessThan(1_500);
  await expect(page.getByText(/Which exact software, standard, or workflow and version/i).last())
    .toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  // A short imperative must reuse the durable semantic blocker. It may not reopen catalog
  // retrieval merely because the buyer says "choose" before answering the material questions.
  await input.fill('Choose a laptop and confirm the purchase order.');
  await input.press('Enter');
  await expect(page.getByText(/Choose a laptop and confirm the purchase order/i).last())
    .toBeVisible({ timeout: 5_000 });
  await expect(page.getByText(/Which exact software, standard, or workflow and version/i).last())
    .toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal).toBeVisible();
  await modal.getByRole('button', { name: /^Reasoning/ }).click();
  const semantic = modal.getByTestId('semantic-resolution-trace');
  await expect(semantic).toBeVisible({ timeout: 30_000 });
  await expect(semantic).toContainText(/digital twin/i);
  await expect(semantic).toContainText(/software, standard, or workflow and version/i);
  await expect(semantic).toContainText(/locally on each device, remotely, or in a hybrid setup/i);
  await expect(semantic).toContainText(/time-to-result target/i);
  await expect(semantic).toContainText(/Catalog authority\s*blocked/i);
  await expect(semantic.getByTestId('semantic-residual-route')).toContainText(/ASK/i);
  await expect(semantic).toContainText(/material buyer input required/i);
  await expect(semantic).toContainText(/Inventory ATP:\s*withheld/i);
  await expect(semantic).toContainText(/supplier enquiry.*commerce execution/i);
});
