import { expect, test } from '@playwright/test';

test.skip(
  process.env.RUN_RESEARCH_DEGRADATION_CERTIFICATION !== '1',
  'Requires the SearX-unreachable degradation backend profile.',
);

test('unreachable discovery degrades to canonical origin without hanging or claiming discovery', async ({ page }) => {
  test.setTimeout(180_000);
  const uid = `degraded-research-${Date.now()}-${Math.random()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need a laptop to simulate a PLC-controlled factory using Factory I/O.');
  await input.press('Enter');
  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible({ timeout: 45_000 });
  await expect(panel).toContainText(/external calls: 0/i);

  const researchResponse = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(new URL(response.url()).pathname)
  ), { timeout: 90_000 });
  await panel.getByRole('button', { name: 'Research approved sources' }).click();
  const response = await researchResponse;
  expect(response.ok()).toBe(true);
  const payload = await response.json();
  expect(payload.research.discovery_readiness.error_code).toBe('discovery_endpoint_unreachable');
  expect(payload.research.provider_accounting.discovery_calls).toBe(0);
  expect(payload.research.provider_accounting.paid_calls).toBe(0);
  expect(
    payload.research.provider_accounting.official_origin_fetches
      + payload.research.provider_accounting.cache_hits,
  ).toBeGreaterThan(0);
  await expect(page.getByTestId('product-shelves')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/approved-source research completed/i)).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Upload requirements' })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Research approved sources' })).toHaveCount(0);
});
