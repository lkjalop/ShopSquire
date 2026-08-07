import { expect, test, type Page } from '@playwright/test';

async function send(page: Page, text: string) {
  const responsePromise = page.waitForResponse(
    response => /\/api\/v1\/chat\/(stream|query)$/.test(response.url()),
    { timeout: 90_000 },
  );
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await input.press('Enter');
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 90_000 });
  const response = await responsePromise;
  const payloads = (await response.text()).split('\n')
    .filter(line => line.startsWith('data: '))
    .map(line => { try { return JSON.parse(line.slice(6)); } catch { return null; } })
    .filter(Boolean);
  return [...payloads].reverse().find((item: any) => item?.decision_trace_id || item?.trace_id) || {};
}

test('selected product explanation and two-day feasibility share one governed trace', async ({ page }) => {
  test.setTimeout(240_000);
  expect((await page.request.get('http://127.0.0.1:8080/healthz')).ok()).toBeTruthy();

  const uid = `fit-deadline-${Date.now()}-${Math.random()}`;
  await page.addInitScript((value) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', value);
  }, uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await send(
    page,
    'Recommend a laptop for predicting mechanical-machine breakdown with an unfamiliar '
      + 'industrial maintenance simulation. '
      + 'Use approved official requirements sources; I consent to that research.',
  );
  const lenovoCard = page.locator('[data-testid="recommendation-shelf"] article')
    .filter({ hasText: 'Lenovo Legion Pro 7' }).first();
  await expect(lenovoCard).toBeVisible({ timeout: 30_000 });
  const add = lenovoCard.getByRole('button', { name: 'Add', exact: true });
  await expect(add).toBeVisible({ timeout: 30_000 });
  await add.click();
  await expect(page.getByText(/has been added to your cart/i)).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('strong').filter({ hasText: 'Lenovo Legion Pro 7 16IAX10H' }).last()).toBeVisible();
  await expect(page.getByText(/\*\*Lenovo Legion Pro 7/)).toHaveCount(0);
  await send(
    page,
    'Actually, can you explain why this is a good choice? I need about 30 of those in 2 days.',
  );
  await expect(page.getByText(/cart stays unchanged until you confirm/i)).toBeVisible();
  await expect(page.getByText(/Set it to exactly 30/i)).toBeVisible();
  await expect(page.getByText(/mechanical-machine breakdown|mechanical-machine maintenance/i).last()).toBeVisible();
  await expect(page.getByText(/bounded qualification/i).last()).toBeVisible();
  await expect(page.getByText(/RAM .*32 GB/i).last()).toBeVisible();
  await expect(page.getByText(/GPU VRAM .*12 GB|GPU VRAM .*8 GB/i).last()).toBeVisible();
  await expect(page.getByText('What budget range should I stay within?', { exact: true })).toHaveCount(0);

  const currentLenovoCard = page.locator('[data-testid="recommendation-shelf"] article')
    .filter({ hasText: 'Lenovo Legion Pro 7' }).first();
  await currentLenovoCard.getByRole('button', { name: 'Why?' }).click();
  const whyDrawer = page.getByText(/Why this product:/).locator('..').locator('..');
  await expect(whyDrawer.getByText(/mechanical-machine breakdown|mechanical-machine maintenance/i)).toBeVisible();
  await expect(whyDrawer.getByRole('region', { name: 'Product workload fit' })).toContainText(/RAM|GPU VRAM/i);
  await whyDrawer.getByRole('button', { name: /close product explanation/i }).click();

  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal).toBeVisible();

  await modal.getByRole('button', { name: /^Research & Fit/ }).click();
  await modal.getByRole('tab', { name: /^Why$/ }).click();
  await expect(modal.getByTestId('trace-fit-ledger')).toContainText(/Selected Product Fit Authorization/i);
  await expect(modal.getByTestId('trace-fit-ledger')).toContainText(/ram|vram/i);

  await modal.getByRole('button', { name: /^Commercial Journey/ }).click();
  await modal.getByRole('tab', { name: /Procurement/ }).click();
  const delivery = modal.getByTestId('trace-delivery-feasibility');
  await expect(delivery).toContainText(/2 day/i);
  await expect(delivery).toContainText(/Unknown/i);
  await expect(delivery).toContainText(/No supplier contact or delivery promise was executed/i);

  await page.screenshot({ path: '../.tmp-fit-deadline-browser/proof.png', fullPage: true });
});
