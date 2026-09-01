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
  const chatResponse = page.waitForResponse(
    response => /\/api\/v1\/chat\/(stream|query)$/.test(response.url()),
    { timeout: 90_000 },
  ).catch(() => null);
  const firstResponse = page.waitForResponse(
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
  const first = await firstResponse;
  if (/\/shopping-cases\/interpretations$/.test(first.url()) && first.status() === 204) {
    const chat = await chatResponse;
    if (chat) await chat.text();
  } else if (/\/chat\/(stream|query)$/.test(first.url())) {
    await first.text();
  }
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
  const researchRequest = page.waitForRequest(
    request => /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(request.url()),
    { timeout: 60_000 },
  );
  await send(page, 'Actually I need to simulate PLCs with Rockwell Emulate3D.');
  const researchPanel = page.getByTestId('ambiguity-exploration');
  await expect(researchPanel).toContainText(/Rockwell Emulate3D/i);
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();

  const explicitResearchButton = researchPanel.getByRole('button', {
    name: /Research approved sources|Discover official sources/i,
  });
  if (await explicitResearchButton.count()) await explicitResearchButton.click();
  expect((await researchRequest).postDataJSON()).toMatchObject({
    research_authorized: true,
  });
  expect((await researchRequest).postDataJSON().authorization_basis).toMatch(
    /tenant_policy|buyer_action/,
  );
  await expect(page.getByText(/Approved-source research (completed|could not complete)/i)).toBeVisible({
    timeout: 45_000,
  });
  await pause(page, 2);

  await send(page, 'Official link: https://store.sim3d.com/demo3d_2025/system_requirements');
  const explicitSourceFetch = page.getByRole('button', {
    name: 'Fetch reviewed canonical source',
  });
  if (await explicitSourceFetch.count()) {
    const sourceFetchResponse = page.waitForResponse(
      response => /\/evidence-source-resolutions$/.test(response.url()),
      { timeout: 90_000 },
    );
    await explicitSourceFetch.click();
    await sourceFetchResponse;
  }
  await expect(page.getByTestId('buyer-requirement-review').first()).toBeVisible({
    timeout: 90_000,
  });
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
  await expect(page.getByTestId('buyer-requirement-review').last()).toBeVisible();
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
    await trace.getByRole('button', { name: 'Research & Fit', exact: true }).click();
    const outcome = trace.getByTestId('research-outcome-summary').first();
    await expect(outcome).toBeVisible();
    await expect(outcome).toContainText(/Discovery:/i);
    await expect(outcome).toContainText(/Parsed:\s*[1-9]/i);
    // Parsed official-origin claims are held for independent review. They may
    // support a visibly provisional exploration, but catalog authority itself
    // remains blocked until a reviewer accepts them for this case.
    await expect(outcome).toContainText(/Held for review/i);
    await expect(outcome).toContainText(/Catalog authority:\s*blocked/i);
    await expect(outcome).toContainText(/Commerce authority:\s*none/i);
    await expect(trace).toContainText(/Authority unrecorded|Proposal only/i);
    await pause(page, 3);
  }
});
