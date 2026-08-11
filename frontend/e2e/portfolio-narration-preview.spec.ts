import { expect, test } from '@playwright/test';

test.skip(
  process.env.RUN_PORTFOLIO_NARRATION_PREVIEW !== '1',
  'Requires the local Qwen portfolio preview profile.',
);

test('local narration is buyer-triggered, critic-accepted and commercially powerless', async ({ page }) => {
  test.setTimeout(180_000);
  const uid = `portfolio-narration-${Date.now()}-${Math.random()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need to simulate a PLC-controlled factory using Factory I/O.');
  await input.press('Enter');

  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible({ timeout: 45_000 });
  await panel.getByRole('button', { name: 'Research approved sources' }).click();
  await expect(page.getByTestId('product-shelves')).toBeVisible({ timeout: 60_000 });

  const previewResponse = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && /\/api\/v1\/shopping-cases\/[^/]+\/narration-preview$/.test(new URL(response.url()).pathname)
  ));
  await page.getByRole('button', { name: 'AI explanation preview' }).click();
  const response = await previewResponse;
  expect(response.ok()).toBe(true);
  const payload = await response.json();
  expect(payload.commercial_authority_granted).toBe(false);
  expect(payload.cart_authority).toBe('none');
  expect(payload.supplier_authority).toBe('none');
  expect(payload.status).toBe('accepted_preview');
  expect(payload.renderer).toBe('local_model_preview');
  expect(payload.buyer_visible_model_copy).toBe(true);
  await expect(page.getByTestId('narration-preview-status')).toContainText(
    /critic accepted.*no commerce authority/i,
  );
});
