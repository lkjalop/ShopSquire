import { expect, test } from '@playwright/test';

const prompts = [
  'I need a portable workstation for the fictional HelioSpec Tandem 9 protein-identification suite; only its publisher requirements may qualify hardware.',
  'Can this notebook run the fictional Oriole FPGA Closure Suite 11? Vendor-supported synthesis and timing requirements are mandatory.',
  'I need a mobile workstation for the fictional GeoStrata Coupled Solver X. Only its publisher requirements may qualify hardware.',
  'My budget is AUD 7000 each for the fictional AsterCal Radio Cube Studio; only officially supported mobile hardware is acceptable.',
  'I need to run the fictional DentVoxel Segmenter Enterprise locally; only its software-publisher hardware requirements are acceptable.',
];

async function openAssistant(page: import('@playwright/test').Page, suffix: string) {
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `open-world-unseen-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
}

for (const [index, prompt] of prompts.entries()) {
  test(`unseen ${index + 1}: consent dispatches free discovery without granting authority`, async ({ page }) => {
    test.setTimeout(180_000);
    await openAssistant(page, `${index}-${Date.now()}`);
    const input = page.getByPlaceholder('Type your message...');
    await input.fill(prompt);
    await input.press('Enter');

    const exploration = page.getByTestId('ambiguity-exploration');
    await expect(exploration).toBeVisible({ timeout: 65_000 });
    await expect(exploration.getByTestId('buyer-research-status'))
      .toContainText(/external research has not produced evidence/i);
    await expect(exploration).toContainText(/external calls: 0/i);
    await expect(page.getByText(/Authorized recommendation/i)).toHaveCount(0);

    const button = exploration.getByRole('button', {
      name: /Discover official sources|Research approved sources/i,
    });
    await expect(button).toBeVisible();
    const responsePromise = page.waitForResponse(
      response => response.request().method() === 'POST'
        && /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(response.url()),
      { timeout: 90_000 },
    );
    await button.click();
    const response = await responsePromise;
    const payload = await response.json();
    expect(response.ok(), JSON.stringify(payload)).toBe(true);
    expect(payload.status).toBe('publisher_resolution_required');
    expect(payload.research.provider_accounting.discovery_calls).toBeGreaterThanOrEqual(2);
    expect(payload.research.provider_accounting.paid_calls).toBe(0);
    expect(payload.qualification_authority ?? 'none').toBe('none');
    expect(payload.research.status).toMatch(/publisher_candidates_found|no_publisher_candidates/);
    for (const candidate of payload.research.candidates || []) {
      expect(candidate.authority).toBe('not_accepted');
    }
  });
}
