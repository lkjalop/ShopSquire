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
  const body = await response.text();
  if ((response.headers()['content-type'] || '').includes('application/json')) {
    try { return JSON.parse(body); } catch { return {}; }
  }
  const payloads = body.split('\n')
    .filter(line => line.startsWith('data: '))
    .map(line => { try { return JSON.parse(line.slice(6)); } catch { return null; } })
    .filter(Boolean);
  return [...payloads].reverse().find((item: any) => item?.decision_trace_id || item?.trace_id) || {};
}

const unresolvedCases = [
  {
    name: 'product noun cannot bypass unresolved workload authority',
    query: 'I need a laptop for digital twin simulation of a cyber attack.',
  },
  {
    name: 'noun-free paraphrase has the same unresolved workload authority',
    query: 'I need something for digital twin simulation of a cyber attack.',
  },
];

for (const scenario of unresolvedCases) {
  test(scenario.name, async ({ page }) => {
    test.setTimeout(150_000);
    const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    await page.addInitScript((uid) => {
      localStorage.clear();
      sessionStorage.clear();
      localStorage.setItem('uid', uid);
      sessionStorage.setItem('uid', uid);
    }, `unresolved-workload-${suffix}`);
    // Keep this semantic authority test single-flight. SSE retry/abort behavior
    // has its own operational suite and must not execute the model twice here.
    await page.route('**/api/v1/chat/stream', route => route.abort());
    await page.goto('/');
    await page.getByRole('button', { name: /Ask Me/i }).click();

    const result = await send(page, scenario.query);
    const traceId = String(result.decision_trace_id || result.trace_id || '');
    expect(traceId).not.toBe('');
    await expect(page.getByText(/current external requirements|approved official sources|cannot qualify/i).first())
      .toBeVisible();
    await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

    await page.getByTitle('Decision Trace').click();
    const modal = page.getByTestId('decision-trace-modal');
    await expect(modal.locator(`[title="${traceId}"]`)).toBeVisible();
    await modal.getByRole('button', { name: /^Research & Fit/ }).click();
    await modal.getByRole('tab', { name: /Research Breakdown/ }).click();
    await expect(modal.getByTestId('workload-research-trace'))
      .toContainText(/uninterpreted|research candidate|consent required/i);
  });
}
