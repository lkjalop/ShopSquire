import { test, expect } from '@playwright/test';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

const here = dirname(fileURLToPath(import.meta.url));
const requirementScreenshot = resolve(
  here,
  '../../dump/ecommerce/New -screenies/55 - product specs ocr.png',
);

test('requirements screenshot becomes reviewable provisional claims', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  await page.addInitScript(
    (uid) => sessionStorage.setItem('uid', uid),
    `enterprise-e2e-upload-${suffix}`,
  );
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await page.locator("input[type='file']").last().setInputFiles(requirementScreenshot);
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('Can you read these specifications?');
  await input.press('Enter');

  const review = page.getByTestId('buyer-requirement-review');
  await expect(review).toBeVisible({ timeout: 90_000 });
  await expect(review).toContainText(/provisional and unverified/i);
  await expect(review.getByRole('textbox', { name: 'Correct ram gb value' }).first()).toHaveValue('32');
  await expect(review.getByRole('textbox', { name: 'Correct storage gb value' }).first()).toHaveValue('1000');
  await expect(review.getByRole('textbox', { name: 'Correct operating system value' })).toHaveValue('Windows 11 Pro');
  await expect(page.getByText(/image content looks unsafe/i)).toHaveCount(0);
  await expect(page.getByText(/provide an approved requirements document/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await review.getByRole('button', { name: 'Use provisionally' }).click();
  const shelves = page.getByTestId('product-shelves');
  await expect(shelves).toBeVisible({ timeout: 30_000 });
  await expect(shelves).toContainText(/provisional exploration/i);
  await expect(shelves).toContainText(/best across accepted shared needs/i);
  await expect(shelves).toContainText(/mobile workstation/i);
  await expect(shelves).toContainText(/evidence freshness/i);
  await expect(page.getByText(/reranked the local catalog without calling an external provider/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);
});
