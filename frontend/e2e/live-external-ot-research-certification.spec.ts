import { test, expect, type Page } from '@playwright/test';

const liveEnabled = process.env.RUN_LIVE_EXTERNAL_CERTIFICATION === '1';

async function send(page: Page, text: string) {
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && /\/api\/v1\/chat\/stream(?:\?|$)/.test(response.url())
  ), { timeout: 120_000 });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await input.press('Enter');
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 120_000 });
  return response.text();
}

test('live OT research stays in one case and exposes real provider receipts', async ({ page }) => {
  test.skip(!liveEnabled, 'requires backend live-research profile and local SearXNG');
  test.setTimeout(300_000);
  const uid = `live-ot-${Date.now()}-${Math.random()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await send(page, 'I need to simulate a PLC-controlled factory and cyberattacks against the OT network.');
  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText(/external calls: 0/i);
  await expect(panel).toContainText(/paid calls: 0/i);
  await expect(panel).not.toContainText(/isaac|physics/i);

  const researchResponse = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && /\/api\/v1\/chat\/stream(?:\?|$)/.test(response.url())
  ), { timeout: 180_000 });
  await panel.getByRole('button', { name: /Research approved sources/i }).click();
  const response = await researchResponse;
  const body = await response.text();
  expect(body).toContain('network_execution');
  expect(body).toContain('fixture');
  expect(body).toContain('provider_endpoint_host');
  expect(body).toContain('response_body_hash');
  expect(body).toMatch(/"network_execution"\s*:\s*true/);
  expect(body).toMatch(/"fixture"\s*:\s*false/);
  expect(body).toMatch(/"paid_calls"\s*:\s*0/);

  await expect(page.getByTestId('product-shelves')).toBeVisible();
  await expect(page.getByText(/research.*rerank|moved.*because/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);
});
