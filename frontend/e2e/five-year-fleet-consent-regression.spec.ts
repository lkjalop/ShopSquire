import { test, expect, type Page } from '@playwright/test';

const exact = 'I want this to last five years as a company laptop fleet. We use Linux sometimes, Windows management, docks and two 4K monitors. Are there any support, compatibility or security reasons not to buy 40 of them?';

const journeys = [
  { id: 'exact-1', prompt: exact },
  { id: 'exact-2', prompt: exact },
  { id: 'exact-3', prompt: exact },
  {
    id: 'personal-one',
    prompt: 'I want one laptop to last five years. I dual boot Linux, use Windows management for work, and connect two 4K monitors through a dock. What support or compatibility risks should I check?',
  },
  {
    id: 'fleet-thirty-days',
    prompt: 'We need 40 company laptops within 30 days. They must be Ubuntu certified, manageable from Windows, support our docks and drive two 4K monitors for five years. Can you qualify the shortlist?',
  },
  {
    id: 'fleet-two-days',
    prompt: 'We need 40 company laptops in two days. Linux support, Windows management, dock compatibility, two 4K monitors and unresolved firmware security issues all matter. What can actually arrive and qualify?',
  },
  {
    id: 'budgeted-fleet',
    prompt: 'Budget is AUD 3,500 each for 40 laptops and we can wait eight weeks. We need five-year vendor support, Linux compatibility, Windows management, docks and two 4K monitors. Show the risks and alternatives.',
  },
  {
    id: 'named-model',
    prompt: 'Should we buy 40 of the shortlisted mobile workstation for a five-year fleet? Verify Linux support, Windows management, dock and dual-4K compatibility, security advisories and warranty before recommending it.',
  },
];

async function openAssistant(page: Page, uid: string) {
  await page.addInitScript((value) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', value);
  }, uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
}

async function createCase(page: Page, prompt: string) {
  const responsePromise = page.waitForResponse(
    response => /\/api\/v1\/shopping-cases\/interpretations$/.test(response.url()),
    { timeout: 30_000 },
  );
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(prompt);
  await input.press('Enter');
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  return response.json();
}

for (const journey of journeys) {
  test(`five-year fleet consent is consequential and bounded: ${journey.id}`, async ({ page }) => {
    test.setTimeout(90_000);
    await openAssistant(page, `fleet-consent-${journey.id}-${Date.now()}-${Math.random()}`);
    const created = await createCase(page, journey.prompt);
    expect(created.ambiguity_exploration.status).toBe('provisional');
    expect(created.provider_accounting).toEqual({ external_calls: 0, paid_calls: 0 });
    expect(created.catalog_candidate_set.configuration_ids.length).toBeGreaterThan(0);
    await expect(page.getByText(/Authorized recommendation/i)).toHaveCount(0);

    const panel = page.getByTestId('ambiguity-exploration');
    const researchButton = panel.getByRole('button', {
      name: /Discover official sources|Research approved sources/i,
    });
    await expect(researchButton).toBeVisible();
    const responsePromise = page.waitForResponse(
      response => /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(response.url()),
      { timeout: 25_000 },
    );
    const startedAt = Date.now();
    await researchButton.click();
    const response = await responsePromise;
    const elapsedMs = Date.now() - startedAt;
    expect(response.ok(), `research failed with ${response.status()}`).toBeTruthy();
    expect(elapsedMs).toBeLessThan(21_000);
    const researched = await response.json();
    expect(researched.status).toMatch(/publisher_resolution_required|research_completed/);
    const accounting = researched.research.provider_accounting;
    expect(accounting.paid_calls).toBe(0);
    // The first run proves outbound discovery/origin fetch. Repeated verbatim and
    // paraphrased runs may legitimately use the governed evidence cache; that is
    // consequential research reuse, not a silent no-op.
    expect(
      Number(accounting.external_calls || 0) + Number(accounting.cache_hits || 0),
    ).toBeGreaterThan(0);
    await expect(panel).not.toContainText(/Status: Provisional/i);
    await expect(page.getByText(/could not complete/i)).toHaveCount(0);
    await expect(page.getByText(/Authorized recommendation/i)).toHaveCount(0);
  });
}
