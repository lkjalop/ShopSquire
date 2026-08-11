import { test, expect } from '@playwright/test';

async function send(page: import('@playwright/test').Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  const responsePromise = page.waitForResponse(
    response => (
      /\/api\/v1\/chat\/(stream|query)$/.test(response.url())
      || /\/api\/v1\/shopping-cases\/interpretations$/.test(response.url())
    ),
    { timeout: 65_000 },
  );
  await input.fill(text);
  await input.press('Enter');
  let response = await responsePromise;
  if (/\/shopping-cases\/interpretations$/.test(response.url())) {
    if (response.status() !== 204) return response.json();
    response = await page.waitForResponse(
      candidate => /\/api\/v1\/chat\/(stream|query)$/.test(candidate.url()),
      { timeout: 65_000 },
    );
  }
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 60_000 });
  const body = await response.text();
  const payloads = body.split('\n')
    .filter(line => line.startsWith('data: '))
    .map(line => {
      try { return JSON.parse(line.slice(6)); } catch { return null; }
    })
    .filter(Boolean);
  return [...payloads].reverse().find(
    (payload: any) => payload?.decision_trace_id || payload?.trace_id,
  ) || {};
}

test('novel suitability request stays provisional and exposes a durable research plan', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-open-world-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const unresolved = await send(
    page,
    'I edit 8K RAW video and do colour-critical grading. I do not care about gaming FPS. Which laptop should I buy?',
  );
  const unresolvedTraceId = String(unresolved.decision_trace_id || unresolved.trace_id || '');
  expect(unresolvedTraceId).not.toBe('');
  expect(unresolved.qualification_authority ?? 'none').toBe('none');

  await expect(page.getByTestId('ambiguity-exploration')).toContainText(/provisional/i);
  await expect(page.getByRole('button', { name: /Discover official sources/i })).toBeVisible();
  await expect(page.getByText(/Authorized recommendation/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);
  await expect(page.getByTestId('ambiguity-accounting')).toContainText(/external calls: 0/i);

  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal.locator(`[title="${unresolvedTraceId}"]`)).toBeVisible();
  await modal.getByRole('button', { name: /^Research & Fit/ }).click();
  await modal.getByRole('tab', { name: /Research Breakdown/ }).click();
  const research = modal.getByTestId('workload-research-trace');
  await expect(research).toContainText(/8K RAW video/i);
  await expect(research).toContainText(/colour-critical grading/i);
  await expect(research).toContainText(/bounded research plan/i);
  await expect(research).toContainText(/Status:\s*(blocked|planned|not executed)/i);
  await expect(research).toContainText(/catalog recommendation|exploration/i);
  await page.screenshot({ path: '../.tmp-open-world-browser/coverage-gate.png', fullPage: true });
});
