import { test, expect } from '@playwright/test';

async function send(page: import('@playwright/test').Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await input.press('Enter');
  await expect(page.getByTestId('stream-acknowledgement')).toBeVisible({ timeout: 1_500 });
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 60_000 });
}

test('unfamiliar capability request plans research before buyer-specific clarification', async ({ page }) => {
  test.setTimeout(300_000);
  // A fresh enterprise-scoped identity gives this real-backend journey an isolated,
  // deterministic allowance. Shared guest quota state must not turn a semantic
  // contract test into an intermittent quota test.
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  const uid = `enterprise-e2e-semantic-${suffix}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const input = page.getByPlaceholder('Type your message...');
  await input.fill('Please recommend a laptop for simulating a digital twin for maintenance of mechanical machines.');
  const started = Date.now();
  await input.press('Enter');

  await expect(page.getByTestId('stream-acknowledgement')).toBeVisible({ timeout: 1_500 });
  expect(Date.now() - started).toBeLessThan(1_500);
  await expect(page.getByText(/needs current external requirements.*approved official sources/i).last())
    .toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await send(page, 'You may research approved official sources for the workload requirements.');
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await send(page, 'The workflow is a local mechanical-maintenance digital twin with engineering simulation and 3D visualisation.');
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await send(page, 'I need about 30 of those and the total budget is AUD 75,000.');
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await send(page, 'Actually reduce it by 10 units, but I do not think that is powerful enough for what I need.');
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal).toBeVisible();
  await modal.getByRole('button', { name: /^Research & Fit/ }).click();
  await modal.getByRole('tab', { name: /Research Breakdown/ }).click();
  const research = modal.getByTestId('workload-research-trace');
  await expect(research).toBeVisible({ timeout: 30_000 });
  await expect(research).toContainText(/digital twin/i);
  await expect(research).toContainText(/bounded research plan/i);
  await expect(research).toContainText(/official requirements/i);
  await expect(research).toContainText(/Consent recorded:\s*Yes/i);
  await expect(research).toContainText(/Status:\s*blocked/i);
  await expect(research).toContainText(/catalog recommendation.*supplier enquiry/i);
  await expect(research).toContainText(/Prior quantity:\s*30/i);
  await expect(research).toContainText(/Proposed value:\s*20/i);
  await expect(research).toContainText(/requires buyer confirmation/i);
});
