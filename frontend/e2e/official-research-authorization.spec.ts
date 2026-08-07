import { test, expect, type Page } from '@playwright/test';

async function send(page: Page, text: string) {
  const responsePromise = page.waitForResponse(
    response => /\/api\/v1\/chat\/(stream|query)$/.test(response.url()),
    { timeout: 65_000 },
  );
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await input.press('Enter');
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 60_000 });
  const response = await responsePromise;
  const payloads = (await response.text()).split('\n')
    .filter(line => line.startsWith('data: '))
    .map(line => { try { return JSON.parse(line.slice(6)); } catch { return null; } })
    .filter(Boolean);
  return [...payloads].reverse().find((item: any) => item?.decision_trace_id || item?.trace_id) || {};
}

test('official evidence compiles into product authorization under one trace', async ({ page }) => {
  test.setTimeout(180_000);
  const health = await page.request.get('http://127.0.0.1:8080/health');
  expect(health.ok()).toBeTruthy();
  const readiness = (await health.json())?.commerce_features?.external_search;
  expect(readiness?.requirement_authority_ready).toBe(true);

  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `official-research-e2e-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const result = await send(
    page,
    'Recommend a laptop for simulation of an unfamiliar industrial maintenance process. '
      + 'Use approved official requirements sources; I consent to that research.',
  );
  const traceId = String(result.decision_trace_id || result.trace_id || '');
  expect(traceId).not.toBe('');
  await expect(page.getByRole('button', { name: 'Add', exact: true }).first()).toBeVisible();

  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal.locator(`[title="${traceId}"]`)).toBeVisible();
  await modal.getByRole('button', { name: /^Research & Fit/ }).click();
  await modal.getByRole('tab', { name: /Research Breakdown/ }).click();
  const research = modal.getByTestId('workload-research-trace');
  await expect(research).toContainText(/official requirements api/i);
  await expect(research).toContainText(/ram gb >= 32 GB/i);
  await expect(research).toContainText(/gpu vram gb >= 8 GB/i);
  await expect(research).toContainText(/Status:\s*accepted/i);
  await page.screenshot({ path: '../.tmp-official-research-browser/proof.png', fullPage: true });
});
