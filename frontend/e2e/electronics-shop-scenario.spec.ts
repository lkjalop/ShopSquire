import { test, expect } from '@playwright/test';

test('quantity expansion displays real API arithmetic without granting commerce authority', async ({ page }) => {
  await page.goto('/?surface=electronics-shop');
  await expect(page.getByRole('heading', { name: 'Electronics shop simulation' })).toBeVisible();
  await page.getByLabel('Requested units').fill('30');
  await page.getByRole('button', { name: 'Assess request' }).click();
  await expect(page.getByTestId('shortfall')).toHaveText('15');
  await page.getByText('Operational history', {exact:true}).click();
  await expect(page.getByTestId('operational-history')).toContainText('store-a: 8 on hand, 2 reserved, 6 available');
  await expect(page.getByTestId('operational-history')).toContainText('sale: 3 units');
  const before = await page.getByTestId('request-digest').textContent();
  await page.getByLabel('Requested units').fill('40');
  await page.getByRole('button', { name: 'Assess request' }).click();
  await expect(page.getByTestId('shortfall')).toHaveText('25');
  await expect(page.getByTestId('request-digest')).not.toHaveText(before!);
  await expect(page.getByText('Delivery unconfirmed · Commerce authority none')).toBeVisible();
  await page.getByLabel('Requested units').fill('100');
  await page.getByRole('button', { name: 'Assess request' }).click();
  await expect(page.getByTestId('shortfall')).toHaveText('85');
  await expect(page.getByText('Still uncovered after this offer: 60 units.')).toBeVisible();
});
