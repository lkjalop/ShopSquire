import { expect, test, type Page } from '@playwright/test';

const RECORDING_PAUSE_MS = Number(process.env.RECORDING_PAUSE_MS || 900);

async function pause(page: Page, multiplier = 1) {
  await page.waitForTimeout(RECORDING_PAUSE_MS * multiplier);
}

async function openFreshBuyer(page: Page, label: string) {
  await page.goto('/');
  await page.evaluate((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `portfolio-recording-${label}-${Date.now()}`);
  await page.reload();
  await page.getByRole('button', { name: /Ask Me/i }).click();
  await expect(page.getByTestId('decision-trace-modal')).toHaveCount(0);
  await pause(page);
}

async function send(page: Page, text: string) {
  const terminalResponse = page.waitForResponse(
    response => (
      /\/api\/v1\/chat\/(stream|query)$/.test(response.url())
      || /\/api\/v1\/shopping-cases\/interpretations$/.test(response.url())
    ),
    { timeout: 90_000 },
  );
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await pause(page, 0.5);
  await input.press('Enter');
  await terminalResponse;
  await pause(page, 2);
}

async function submitBridge(page: Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await pause(page, 0.5);
  await input.press('Enter');
}

test('deterministic portfolio recording walkthrough', async ({ page }) => {
  test.setTimeout(600_000);

  await openFreshBuyer(page, 'gaming');
  await send(page, 'I need a gaming laptop. Is AUD 4,000 okay?');
  await expect(page.getByText(/Target-price fit/i).first()).toBeVisible();
  await expect(page.getByText(/Qualified value options/i).first()).toBeVisible();
  await pause(page, 2);

  await openFreshBuyer(page, 'university');
  await send(page, 'I need a portable laptop for university assignments and video calls under AUD 1,800.');
  await expect(page.getByText(/Found \d+ products/i).first()).toBeVisible();

  await openFreshBuyer(page, 'corporate');
  await send(page, 'Recommend a business laptop for corporate office work and travel under AUD 2,200.');
  await expect(page.getByText(/Found \d+ products/i).first()).toBeVisible();

  await openFreshBuyer(page, 'emulate3d');
  await send(page, 'I need a gaming laptop. Is AUD 4,000 okay?');
  await send(page, 'Actually I need to simulate PLCs with Rockwell Emulate3D.');
  const researchPanel = page.getByTestId('ambiguity-exploration');
  await expect(researchPanel).toContainText(/Rockwell Emulate3D/i);
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();

  const researchRequest = page.waitForRequest(
    request => /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(request.url()),
    { timeout: 30_000 },
  );
  await researchPanel.getByRole('button', { name: /Research approved sources/i }).click();
  expect((await researchRequest).postDataJSON()).toMatchObject({
    research_authorized: true,
    authorization_basis: 'buyer_action',
  });
  await expect(page.getByText(/Approved-source research (completed|could not complete)/i)).toBeVisible({
    timeout: 45_000,
  });
  await pause(page, 2);

  const sourceResponse = page.waitForResponse(
    response => /\/evidence-source-resolutions$/.test(response.url()),
    { timeout: 90_000 },
  );
  await submitBridge(page, 'Official link: https://store.sim3d.com/demo3d_2025/system_requirements');
  const sourcePayload = await (await sourceResponse).json();
  expect(sourcePayload.resolution?.status).toBe('resolved');
  expect(sourcePayload.resolution?.selected_source_id).toBe(
    'rockwell_emulate3d_official_requirements',
  );
  await pause(page, 2);

  const specificationResponse = page.waitForResponse(
    response => /\/requirement-proposals\/from-text$/.test(response.url()),
    { timeout: 60_000 },
  );
  await submitBridge(
    page,
    'Recommended hardware: 64 GB RAM, Windows 11, Nvidia RTX 5000 GPU, '
      + '8-core processor at 5 GHz, 4 TB SSD and high-performance Ethernet adapter.',
  );
  const specificationPayload = await (await specificationResponse).json();
  expect(specificationPayload.claims?.length || 0).toBeGreaterThan(0);
  await expect(page.getByTestId('buyer-requirement-review')).toBeVisible();
  await expect(page.getByText(/provisional requirement claims/i)).toBeVisible();
  await pause(page, 2);

  const proofToggle = page.getByText(/View research proof/i).first();
  if (await proofToggle.isVisible()) {
    await proofToggle.click();
    await pause(page, 2);
  }

  const traceButton = page.getByTitle('Decision Trace');
  if (await traceButton.isEnabled()) {
    await traceButton.click();
    const trace = page.getByTestId('decision-trace-modal');
    await expect(trace).toBeVisible();
    await expect(trace).toContainText(/Not executed/i);
    await expect(trace).toContainText(/Authority unrecorded|Proposal only/i);
    await pause(page, 3);
  }
});
