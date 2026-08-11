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

test('unresolved open-world workload clears stale commercial state before research', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-open-world-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await send(page, 'I need 30 gaming laptops under AUD 2500 each.');
  if (await page.getByRole('button', { name: 'Add', exact: true }).count() === 0) {
    // The stale commercial context is setup, not the behavior under test. One bounded retry
    // tolerates a cold local-model stall while preserving the exact buyer turn.
    await send(page, 'I need 30 gaming laptops under AUD 2500 each.');
  }
  await expect(page.getByRole('button', { name: 'Add', exact: true }).first()).toBeVisible();

  const unresolved = await send(
    page,
    'I need help with a laptop for digital twin simulation? I need it to simulate a cyber attack?',
  );
  const unresolvedTraceId = String(unresolved.decision_trace_id || unresolved.trace_id || '');
  expect(unresolvedTraceId).not.toBe('');
  expect(unresolved.requested_quantity ?? null).toBeNull();

  const assistantMessages = page.locator('[class*="message"][class*="assistant"] [class*="messageContent"]');
  const latest = assistantMessages.last();
  await expect(latest).toContainText(/provisional shopping case/i);
  await expect(latest).not.toContainText(/30 units|for gaming/i);
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);
  await expect(page.getByTestId('ambiguity-accounting')).toContainText(/external calls: 0/i);

  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal.locator(`[title="${unresolvedTraceId}"]`)).toBeVisible();
  await modal.getByRole('button', { name: /^Research & Fit/ }).click();
  await modal.getByRole('tab', { name: /Research Breakdown/ }).click();
  const research = modal.getByTestId('workload-research-trace');
  await expect(research).toContainText(/digital twin simulation/i);
  await expect(research).toContainText(/simulate a cyber attack/i);
  await expect(research).toContainText(/bounded research plan/i);
  await expect(research).toContainText(/Status:\s*(blocked|planned|not executed)/i);
  await expect(research).toContainText(/catalog recommendation|exploration/i);
  await page.screenshot({ path: '../.tmp-open-world-browser/coverage-gate.png', fullPage: true });
});
