import { test, expect, type Page } from '@playwright/test';

const liveEnabled = process.env.RUN_LIVE_EXTERNAL_CERTIFICATION === '1';

async function send(page: Page, text: string) {
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && /\/api\/v1\/(?:chat\/stream|shopping-cases\/interpretations)(?:\?|$)/.test(response.url())
  ), { timeout: 20_000 });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await input.press('Enter');
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 20_000 });
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
      && /\/api\/v1\/shopping-cases\/[^/]+\/research(?:\?|$)/.test(response.url())
  ), { timeout: 180_000 });
  await panel.getByRole('button', { name: /Research approved sources/i }).click();
  const response = await researchResponse;
  expect(response.ok(), `research request failed: ${response.status()}`).toBeTruthy();
  const result = await response.json();
  expect(result.status).toBe('research_completed');
  expect(['live_network', 'evidence_cache']).toContain(result.research.execution_mode);
  if (result.research.execution_mode === 'live_network') {
    expect(result.research.provider_accounting.external_calls).toBeGreaterThanOrEqual(2);
  } else {
    expect(result.research.provider_accounting.cache_hits).toBeGreaterThan(0);
  }
  expect(result.research.provider_accounting.paid_calls).toBe(0);
  expect(result.research.claims.length).toBeGreaterThan(0);
  expect(result.cart_mutation).toBe('not_authorized');
  for (const receipt of result.research.receipts.filter((row: any) => (
    row.execution_status === 'completed' && row.network_execution
  ))) {
    expect(receipt.fixture).toBe(false);
    expect(receipt.provider_endpoint_host).toBeTruthy();
    expect(receipt.response_body_hash).toBeTruthy();
  }

  await expect(page.getByTestId('product-shelves')).toBeVisible();
  await expect(page.getByTestId('research-reranking-delta')).toBeVisible();
  await expect(panel).toContainText(/status: researched/i);
  await expect(panel).toContainText(/paid calls: 0/i);

  // Research changes evidence and ranking only. Commercial continuation has its
  // own portfolio certification and must not be smuggled into this proof.
  await expect(page.getByTestId('pending-cart-change')).toHaveCount(0);
  await expect(page.getByText(/Cart \(0\)/i).first()).toBeVisible();
});
