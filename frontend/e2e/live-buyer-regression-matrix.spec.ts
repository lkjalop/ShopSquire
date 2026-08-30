import { expect, test, type Browser, type Page } from '@playwright/test';

async function openBuyer(browser: Browser, label: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `live-matrix-${label}-${Date.now()}-${Math.random()}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  return { context, page };
}

async function send(page: Page, text: string) {
  // Interpretations are a persistence/preflight operation.  The completed
  // revision-bound buyer projection is the chat answer envelope; accepting an
  // interpretation response here reproduced the production UI race where a
  // partial record briefly replaced the completed turn.
  const chatResponse = page.waitForResponse(
    response => /\/api\/v1\/chat\/(stream|query)$/.test(response.url()),
    { timeout: 90_000 },
  );
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await input.press('Enter');
  const response = await chatResponse;
  const body = await response.text();
  if (!body.includes('data:')) return JSON.parse(body);
  const frames = body.replaceAll('\r\n', '\n').split('\n\n');
  for (const frame of frames.reverse()) {
    if (!frame.includes('event: answer')) continue;
    const raw = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
    if (raw) return JSON.parse(raw);
  }
  throw new Error('No answer frame was returned.');
}

test('covered gaming, university, and corporate searches stay on the normal buyer path', async ({ browser }) => {
  test.setTimeout(300_000);
  const scenarios = [
    {
      label: 'gaming',
      query: 'help me with a gaming laptop? is 4000 ok?',
      answer: /option|match|gaming|laptop|budget/i,
      product: /gaming laptop/i,
    },
    {
      label: 'university',
      query: 'I need a portable laptop for university assignments and video calls under $1800.',
      answer: /laptop|option|fit|budget/i,
      product: /laptop|macbook/i,
    },
    {
      label: 'university-4000-target',
      query: 'I need a 4000 laptop for university?',
      answer: /laptop|option|fit|budget|university|product|ram|battery/i,
      product: /laptop|macbook/i,
    },
    {
      label: 'corporate',
      query: 'Recommend a business laptop for corporate office work and travel under $2200.',
      answer: /laptop|option|fit|budget/i,
      product: /laptop|macbook/i,
    },
  ];

  for (const scenario of scenarios) {
    const { context, page } = await openBuyer(browser, scenario.label);
    const answer = await send(page, scenario.query);
    expect(String(answer.assistant_message || '')).toMatch(scenario.answer);
    expect(answer.products?.length || 0).toBeGreaterThan(0);
    expect((answer.products || []).slice(0, 3).map((item: any) => item.name || item.title).join(' ')).toMatch(scenario.product);
    if (scenario.label === 'gaming') {
      expect(answer.price_intent).toMatchObject({
        mode: 'affordability_check', target: 4000, preferred_min: 3000, hard_ceiling: 4000,
      });
      await expect(page.getByText(/Target-price fit/i).first()).toBeVisible();
      await expect(page.getByText(/Qualified value options/i).first()).toBeVisible();
      expect(String(answer.assistant_message || '')).toMatch(/^Yes - AUD 4,000 is enough/i);
      await expect(page.getByTestId('response-provenance')).toContainText(/deterministic policy/i);
    }
    expect(answer.ambiguity_exploration).toBeFalsy();
    await expect(page.getByTestId('ambiguity-exploration')).toHaveCount(0);
    await context.close();
  }
});

test('a Rockwell Emulate3D pivot supersedes gaming and dispatches enrolled research with buyer authorization', async ({ browser }) => {
  test.setTimeout(300_000);
  const { context, page } = await openBuyer(browser, 'emulate3d-pivot');
  const gaming = await send(page, 'help me with a gaming laptop? is 4000 ok?');
  expect(gaming.ambiguity_exploration).toBeFalsy();

  const researchRequest = page.waitForRequest(
    request => /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(request.url()),
    { timeout: 60_000 },
  );
  const emulate = await send(
    page,
    'actually i need something to simulate PLCs? what do you know of Rockwell Emulate3D?',
  );
  const emulateCaseId = emulate.shopping_case_id || emulate.ambiguity_exploration?.case_id;
  expect(emulateCaseId).toBeTruthy();
  if (gaming.shopping_case_id) expect(emulateCaseId).not.toBe(gaming.shopping_case_id);
  expect(emulate.shopping_case_retained_purpose).toMatch(/Rockwell Emulate3D/i);
  expect(emulate.decision?.subject_action).toBe('switch');
  expect(emulate.clarification_relation).toBe('supersede');
  expect(emulate.products || []).toHaveLength(0);
  expect(String(emulate.assistant_message || '')).toMatch(/new workload.*cleared the earlier gaming assumptions/i);
  expect(emulate.ambiguity_exploration?.source_candidate_ids?.[0]).toBe(
    'rockwell_emulate3d_official_requirements',
  );

  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toContainText(/Rockwell Emulate3D/i);
  await expect(page.getByTestId('product-shelves')).toHaveCount(0);
  const explicitResearchButton = panel.getByRole('button', { name: /Research approved sources/i });
  if (await explicitResearchButton.count()) await explicitResearchButton.click();
  const dispatched = await researchRequest;
  expect(dispatched.postDataJSON()).toMatchObject({
    research_authorized: true,
    research_plan_id: emulate.ambiguity_exploration.research_plan_id,
  });
  expect(dispatched.postDataJSON().authorization_basis).toMatch(/buyer_action|tenant_policy/);
  await expect(page.getByText(
    /Approved-source research (?:completed|could not complete)/i,
  ).last()).toBeVisible({ timeout: 40_000 });
  await expect(page.getByTestId('product-shelves')).toHaveCount(0);
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
  await context.close();
});

test('BG3 affordability plus Emulate3D additive workload retains budget and researches the combined case', async ({ browser }) => {
  test.setTimeout(300_000);
  const { context, page } = await openBuyer(browser, 'bg3-emulate3d-additive');

  const bg3 = await send(page, "Is AUD 3,000 excessive for Baldur's Gate 3");
  expect(bg3.confirmed_slots?.budget_max).toBe(3000);
  expect(bg3.price_intent).toMatchObject({
    mode: 'affordability_check', target: 3000, hard_ceiling: 3000,
  });
  expect(String(bg3.assistant_message || '')).toMatch(
    /(?:AUD\s*)?\$?3,000 is ample for Baldur's Gate 3/i,
  );
  expect(bg3.products?.length || 0).toBeGreaterThan(0);
  expect(bg3.workload_authorization?.evidence?.[0]).toMatchObject({
    canonical_title: "Baldur's Gate 3",
    publisher: 'Larian Studios',
    app_id: '1086940',
    release_state: 'released',
    requirements_completeness: 'minimum_and_recommended',
  });

  const researchRequest = page.waitForRequest(
    request => /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(request.url()),
    { timeout: 60_000 },
  );
  const combined = await send(page, 'It must run Rockwell Emulate3D locally as well');
  expect(combined.shopping_case_id).toBe(bg3.shopping_case_id);
  expect(combined.confirmed_slots?.budget_max).toBe(3000);
  expect(combined.case_additive_workload).toMatchObject({
    status: 'retained_and_added',
    commerce_authority: 'none',
  });
  expect(combined.case_additive_workload?.combined_purpose).toMatch(
    /Baldur's Gate 3.*Rockwell Emulate3D/i,
  );
  expect(combined.products || []).toHaveLength(0);
  expect(combined.ambiguity_exploration).toMatchObject({
    status: 'provisional',
    evidence: 'partial_identity_material_gap',
  });

  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toContainText(/Baldur's Gate 3/i);
  await expect(panel).toContainText(/Rockwell Emulate3D/i);
  await expect(page.getByTestId('product-shelves')).toHaveCount(0);
  const dispatched = await researchRequest;
  expect(dispatched.postDataJSON()).toMatchObject({
    research_authorized: true,
    authorization_basis: 'tenant_policy',
    research_plan_id: combined.ambiguity_exploration.research_plan_id,
  });
  await expect(page.getByText(
    /Approved-source research (?:completed|could not complete)/i,
  )).toBeVisible({ timeout: 40_000 });
  await context.close();
});

test('natural workload replacements advance one revision and never project the prior subject', async ({ browser }) => {
  test.setTimeout(360_000);
  const { context, page } = await openBuyer(browser, 'natural-workload-replacements');

  const bg3 = await send(page, "Is AUD 3,000 excessive for Baldur's Gate 3?");
  expect(bg3.workload_authorization?.evidence?.[0]).toMatchObject({
    canonical_title: "Baldur's Gate 3",
    provider_id: 'steam',
    requirements_completeness: 'minimum_and_recommended',
  });
  expect(bg3.workload_authorization?.evidence?.[0]?.compiled_requirements?.length || 0)
    .toBeGreaterThan(0);
  expect(String(bg3.assistant_message || '')).toMatch(/\$3,000 is ample for Baldur's Gate 3/i);
  expect(bg3.products?.length || 0).toBeGreaterThan(0);
  expect(bg3.ambiguity_exploration || null).toBeNull();
  expect(bg3.case_memory?.read_model?.objective || bg3.shopping_case_retained_purpose)
    .toMatch(/Baldur'?s Gate 3/i);

  const emulate = await send(page, 'What about Rockwell Emulate3D running locally?');
  expect(emulate.case_memory?.transition).toBe('REPLACE_WORKLOAD');
  expect(Number(emulate.case_memory?.version || emulate.case_revision || 0)).toBeGreaterThan(0);
  expect(emulate.case_memory?.read_model?.objective || emulate.shopping_case_retained_purpose)
    .toMatch(/Rockwell Emulate3D/i);
  expect(JSON.stringify(emulate.case_memory?.read_model || {})).not.toMatch(/Baldur'?s Gate 3/i);
  expect(emulate.products || []).toHaveLength(0);

  const agisoft = await send(
    page,
    'I process large drone surveys in Agisoft Metashape. What hardware do I need?',
  );
  expect(agisoft.case_memory?.transition).toBe('REPLACE_WORKLOAD');
  expect(Number(agisoft.case_memory?.version || agisoft.case_revision || 0)).toBeGreaterThan(0);
  expect(agisoft.case_memory?.read_model?.objective || agisoft.shopping_case_retained_purpose)
    .toMatch(/Agisoft Metashape/i);
  expect(JSON.stringify(agisoft.case_memory?.read_model || {})).not.toMatch(/Rockwell Emulate3D/i);
  expect(agisoft.products || []).toHaveLength(0);
  await expect(page.getByTestId('ambiguity-exploration')).toContainText(/Agisoft Metashape/i);
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
  await context.close();
});

test('chat-pasted official URL and specifications enter their governed review paths', async ({ browser }) => {
  test.setTimeout(300_000);
  const { context, page } = await openBuyer(browser, 'emulate3d-paste-bridges');
  await send(page, 'I need a laptop for Rockwell Emulate3D PLC digital twin simulation.');

  const sourceAnswer = await send(
    page,
    'Official link: https://store.sim3d.com/demo3d_2025/system_requirements',
  );
  const sourcePayload = sourceAnswer.buyer_evidence_source_resolution;
  const input = page.getByPlaceholder('Type your message...');
  expect(sourcePayload.resolution?.status).toBe('resolved');
  expect(sourcePayload.resolution?.selected_source_id).toBe(
    'rockwell_emulate3d_official_requirements',
  );
  expect(sourcePayload.resolution?.candidates?.[0]?.match_basis).toBe('enrolled_domain');
  let canonicalFetchPayload = sourcePayload;
  if (sourcePayload.research_status === 'not_authorized') {
    await expect(page.getByText(/safely matched the submitted link to a reviewed canonical publisher source/i)).toBeVisible();
    const canonicalFetchResponse = page.waitForResponse(
      response => /\/evidence-source-resolutions$/.test(response.url()),
      { timeout: 90_000 },
    );
    await page.getByRole('button', { name: 'Fetch reviewed canonical source' }).click();
    canonicalFetchPayload = await (await canonicalFetchResponse).json();
  }
  expect(canonicalFetchPayload.research_status).toBe('claims_pending_review');
  expect(canonicalFetchPayload.claims?.length || 0).toBeGreaterThanOrEqual(8);
  expect(canonicalFetchPayload.canonical_truth).toMatchObject({
    research_execution: 'OFFICIAL_FETCH_PARTIAL',
    evidence_status: 'OBSERVED_PENDING_REVIEW',
    commerce_authority: 'NONE',
  });
  expect(canonicalFetchPayload.source_intake_certificate?.security?.status).toMatch(
    /observed_untrusted_content_pending_compilation|fetch_failed_closed/,
  );
  await expect(page.getByText(/source intake|official source recognized|research status/i).first()).toBeVisible();

  const specificationResponse = page.waitForResponse(
    response => /\/requirement-proposals\/from-text$/.test(response.url()),
    { timeout: 60_000 },
  );
  await input.fill(
    'Recommended hardware: 64 GB RAM, Windows 11, Nvidia RTX 5000 GPU, '
      + '8-core processor at 5 GHz, 4 TB SSD and high-performance Ethernet adapter.',
  );
  await input.press('Enter');
  const specificationPayload = await (await specificationResponse).json();
  expect(specificationPayload.claims?.length || 0).toBeGreaterThan(0);
  await expect(page.getByTestId('buyer-requirement-review').last()).toBeVisible();
  await expect(page.getByText(/I extracted .* provisional requirement claims/i)).toBeVisible();
  await context.close();
});

test('light and strenuous Emulate3D scopes remain separate and fail closed before evidence', async ({ browser }) => {
  test.setTimeout(300_000);
  const prompts = [
    'I need a mobile laptop for light Rockwell Emulate 3D training with one small PLC demo cell.',
    'I need a workstation for strenuous Rockwell Emulate 3D simulation of a large factory with many PLCs and concurrent 3D models.',
  ];
  const cases: string[] = [];
  for (const [index, prompt] of prompts.entries()) {
    const { context, page } = await openBuyer(browser, `emulate3d-scale-${index}`);
    const answer = await send(page, prompt);
    expect(answer.ambiguity_exploration?.retained_purpose).toBe(prompt);
    expect(answer.products || []).toHaveLength(0);
    expect(answer.cart_mutation || 'not_authorized').not.toBe('executed');
    expect(answer.ambiguity_exploration?.source_candidate_ids?.[0]).toBe(
      'rockwell_emulate3d_official_requirements',
    );
    cases.push(String(answer.shopping_case_id || answer.ambiguity_exploration?.case_id));
    await context.close();
  }
  expect(cases[0]).not.toBe(cases[1]);
});
