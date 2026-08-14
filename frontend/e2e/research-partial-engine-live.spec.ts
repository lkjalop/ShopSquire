import { expect, test } from '@playwright/test';

test.skip(
  process.env.RUN_PARTIAL_ENGINE_CERTIFICATION !== '1',
  'Requires live SearXNG with at least one degraded engine and one responding engine.',
);

test('one failed search engine remains visible while free discovery succeeds', async ({ page }) => {
  test.setTimeout(180_000);
  const uid = `partial-engine-${Date.now()}-${Math.random()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(
    'I need a portable laptop for protein identification from tandem mass-spectrometry data.',
  );
  await input.press('Enter');

  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible({ timeout: 65_000 });
  await expect(panel).toContainText(/external calls: 0/i);
  const responsePromise = page.waitForResponse(
    response => response.request().method() === 'POST'
      && /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(response.url()),
    { timeout: 90_000 },
  );
  await panel.getByRole('button', {
    name: /Discover official sources|Research approved sources/i,
  }).click();
  const response = await responsePromise;
  const payload = await response.json();
  expect(response.ok(), JSON.stringify(payload)).toBe(true);
  expect(payload.research.provider_accounting.discovery_calls).toBeGreaterThan(0);
  expect(payload.research.provider_accounting.paid_calls).toBe(0);
  const receipts = payload.research.receipts || [];
  expect(receipts.some((row: any) => Number(row.allowlisted_result_count || 0) > 0)).toBe(true);
  const failures = receipts.flatMap((row: any) => row.engine_failures || []);
  expect(failures.length).toBeGreaterThan(0);

  await page.getByTitle('Decision Trace').click();
  const trace = page.getByTestId('decision-trace-modal');
  await expect(trace).toBeVisible();
  await trace.getByRole('button', { name: 'Research & Fit' }).click();
  await expect(trace).toContainText(failures[0].engine, { timeout: 30_000 });
  await expect(trace).toContainText(/Paid calls:\s*0/i);
});
