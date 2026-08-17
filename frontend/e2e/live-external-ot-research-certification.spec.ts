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

test('live OT research stays in one case and exposes real provider receipts', async ({ page }, testInfo) => {
  test.skip(!liveEnabled, 'requires backend live-research profile and local SearXNG');
  test.setTimeout(300_000);
  const requiredProfile = process.env.CERTIFICATION_RUNTIME_PROFILE;
  expect(
    requiredProfile,
    'configuration failure: set CERTIFICATION_RUNTIME_PROFILE to the expected backend profile',
  ).toBeTruthy();
  const readinessResponse = await page.request.get('/health');
  expect(readinessResponse.ok(), 'configuration failure: backend readiness endpoint unavailable').toBeTruthy();
  const readiness = await readinessResponse.json();
  expect(
    readiness.runtime_modes?.profile,
    'configuration failure: backend runtime profile does not match the certificate',
  ).toBe(requiredProfile);
  expect(readiness.commerce_features?.external_search?.enabled).toBe(true);
  expect(readiness.commerce_features?.external_search?.effective).toBe(true);
  await testInfo.attach('runtime-profile.json', {
    body: Buffer.from(JSON.stringify({
      schema_version: 'browser-runtime-profile-v1',
      git_head: process.env.CERTIFICATION_GIT_HEAD || 'not_recorded',
      recorded_at: new Date().toISOString(),
      runtime_profile: requiredProfile,
      external_search: readiness.commerce_features.external_search,
    }, null, 2)),
    contentType: 'application/json',
  });
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
  expect(result.procurement_decision_run.persistence_status).toBe('persisted');
  expect(result.procurement_decision_run.case_id).toBe(result.case_id);
  expect(result.procurement_decision_run.evidence_watermarks.length).toBeGreaterThan(0);
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

  const historyResponse = await page.request.get(
    `/api/v1/shopping-cases/${result.case_id}/decision-runs?uid=${encodeURIComponent(uid)}`,
  );
  expect(historyResponse.ok()).toBeTruthy();
  const history = await historyResponse.json();
  expect(history.history_count).toBeGreaterThanOrEqual(1);
  expect(history.latest.case_revision).toBe(result.procurement_decision_run.case_revision);
  expect(history.latest.stage_receipts.length).toBeGreaterThanOrEqual(6);
  expect(history.latest.evidence_watermarks.length).toBeGreaterThan(0);
  expect(history.dependency_edges.length).toBeGreaterThan(0);
  expect(history.latest.commercial_authority_granted).toBe(false);
});
