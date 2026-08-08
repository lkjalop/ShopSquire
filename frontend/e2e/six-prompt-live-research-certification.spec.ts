import { test, expect, type Page } from '@playwright/test';

const liveEnabled = process.env.RUN_LIVE_SIX_PROMPT_CERTIFICATION === '1';

type Scenario = {
  name: string;
  prompt: string;
  expectedSources: string[];
  forbiddenSources: string[];
  minimumProductClaims: number;
};

const scenarios: Scenario[] = [
  {
    name: 'manufacturing digital twin and predictive maintenance',
    prompt: 'I need a laptop for digital-twin simulation of factory equipment and predicting breakdowns.',
    expectedSources: ['nist_manufacturing_digital_twins'],
    forbiddenSources: ['mitre_attack_ics', 'factory_io_official_docs'],
    minimumProductClaims: 0,
  },
  {
    name: 'CGI rendering',
    prompt: "I do CGI; I don't want renders taking all night.",
    expectedSources: ['blender_official_requirements'],
    forbiddenSources: ['mitre_attack_ics', 'factory_io_official_docs'],
    minimumProductClaims: 1,
  },
  {
    name: 'large CAD and point clouds',
    prompt: 'I need CAD for very large 3D models and point-cloud work.',
    expectedSources: ['autodesk_autocad_requirements'],
    forbiddenSources: ['mitre_attack_ics', 'factory_io_official_docs'],
    minimumProductClaims: 1,
  },
  {
    name: 'PLC factory and OT cyber range',
    prompt: 'I need to simulate a PLC-controlled factory and cyberattacks against the OT network.',
    expectedSources: ['factory_io_official_docs', 'mitre_attack_ics'],
    forbiddenSources: ['nvidia_omniverse_isaac_docs'],
    minimumProductClaims: 1,
  },
  {
    name: 'large BIM and real-time walkthroughs',
    prompt: "I'm an architect working with large BIM models and real-time walkthroughs.",
    expectedSources: ['autodesk_revit_requirements'],
    forbiddenSources: ['mitre_attack_ics', 'factory_io_official_docs'],
    minimumProductClaims: 1,
  },
  {
    name: 'Unreal Engine Nanite and Lumen',
    prompt: 'I build Unreal Engine games with Nanite and Lumen.',
    expectedSources: ['epic_unreal_engine_requirements'],
    forbiddenSources: ['mitre_attack_ics', 'factory_io_official_docs'],
    minimumProductClaims: 1,
  },
];

async function send(page: Page, prompt: string) {
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && /\/api\/v1\/shopping-cases\/interpretations(?:\?|$)/.test(response.url())
  ), { timeout: 20_000 });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(prompt);
  await input.press('Enter');
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();
  const requestBody = response.request().postDataJSON();
  expect(requestBody).toEqual(expect.objectContaining({ uid: expect.any(String), retained_purpose: prompt }));
  expect(requestBody).not.toHaveProperty('workload');
  const result = await response.json();
  expect(result.provider_accounting).toEqual({ external_calls: 0, paid_calls: 0 });
  expect(result.cart_mutation).toBe('not_authorized');
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 20_000 });
}

for (const scenario of scenarios) {
  test(`live case-bound research: ${scenario.name}`, async ({ page }) => {
    test.skip(!liveEnabled, 'requires reviewed source policies, local SearXNG, and live backend');
    test.setTimeout(420_000);
    const uid = `six-live-${Date.now()}-${Math.random()}`;
    await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
    await page.goto('/');
    await page.getByRole('button', { name: /Ask Me/i }).click();
    await send(page, scenario.prompt);

    const panel = page.getByTestId('ambiguity-exploration');
    await expect(panel).toBeVisible();
    await expect(panel).toContainText(/external calls: 0/i);
    await expect(panel).toContainText(/paid calls: 0/i);
    await expect(panel.getByTestId('research-resolution-owners')).toContainText(/research/i);

    const responsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && /\/api\/v1\/shopping-cases\/[^/]+\/research(?:\?|$)/.test(response.url())
    ), { timeout: 180_000 });
    await panel.getByRole('button', { name: /Research approved sources/i }).click();
    const response = await responsePromise;
    const requestBody = response.request().postDataJSON();
    expect(requestBody).toMatchObject({ research_authorized: true });
    expect(requestBody.research_plan_id).toMatch(/^crp-[a-f0-9]{20}$/);
    expect(requestBody.ambiguity_object_ids.length).toBeGreaterThan(0);
    expect(requestBody.hypothesis_ids.length).toBeGreaterThan(0);
    expect(requestBody).not.toHaveProperty('workload');
    expect(requestBody).not.toHaveProperty('retained_purpose');

    const responseText = await response.text();
    expect(response.ok(), `research failed with ${response.status()}: ${responseText}`).toBeTruthy();
    const result = JSON.parse(responseText);
    const caseId = response.url().match(/shopping-cases\/([^/]+)\/research/)?.[1];
    expect(result.case_id).toBe(caseId);
    expect(result.research.research_plan_id).toBe(requestBody.research_plan_id);
    expect(result.research.provider_accounting.paid_calls).toBe(0);
    expect(result.research.provider_accounting.external_calls).toBeGreaterThanOrEqual(2);
    for (const sourceId of scenario.expectedSources) {
      expect(result.research.source_ids).toContain(sourceId);
    }
    for (const sourceId of scenario.forbiddenSources) {
      expect(result.research.source_ids).not.toContain(sourceId);
    }
    const acceptedEvidence = [
      ...(result.research.claims || []),
      ...(result.research.context_claims || []),
    ];
    expect(acceptedEvidence.length).toBeGreaterThan(0);
    for (const sourceId of scenario.expectedSources) {
      expect(acceptedEvidence.map((row: any) => row.source_id)).toContain(sourceId);
    }
    expect(result.research.claims.length).toBeGreaterThanOrEqual(scenario.minimumProductClaims);
    for (const receipt of result.research.receipts.filter((row: any) => row.execution_status === 'completed')) {
      expect(receipt.fixture).toBe(false);
      expect(receipt.network_execution).toBe(true);
      expect(receipt.query_id).toBeTruthy();
      expect(receipt.query_hash).toBeTruthy();
      expect(receipt.response_body_hash).toBeTruthy();
      if (receipt.provider_capability === 'OFFICIAL_ORIGIN_FETCH') {
        expect(receipt.selected_origin_urls.length).toBeGreaterThan(0);
        expect(receipt.selected_origin_urls[0]).toMatch(/^https:\/\//);
      }
    }
    for (const row of result.research_delta) {
      expect(row.reason).toBeTruthy();
    }
    expect(result.cart_mutation).toBe('not_authorized');
    expect(result.supplier_send).toBe('not_authorized');
    await expect(page.getByTestId('research-reranking-delta')).toBeVisible();
  });
}
