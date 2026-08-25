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
  // The interpretation route may itself return the terminal governed outcome.
  // Absorb the unused chat waiter in that branch so closing the isolated buyer
  // context cannot turn a successful interpretation into an unhandled rejection.
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
  await input.press('Enter');
  const first = await firstResponse;
  if (/\/shopping-cases\/interpretations$/.test(first.url()) && first.status() !== 204) {
    return first.json();
  }
  const response = /\/chat\/(stream|query)$/.test(first.url()) ? first : await chatResponse;
  if (!response) throw new Error('No terminal chat response was returned.');
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
      minPrice: 3000,
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
    if (scenario.minPrice) {
      expect(Math.min(...answer.products.map((item: any) => Number(item.price || 0)))).toBeGreaterThanOrEqual(
        scenario.minPrice,
      );
    }
    expect((answer.products || []).slice(0, 3).map((item: any) => item.name || item.title).join(' ')).toMatch(scenario.product);
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
  const researchRequest = page.waitForRequest(
    request => /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(request.url()),
    { timeout: 30_000 },
  );
  await panel.getByRole('button', { name: /Research approved sources/i }).click();
  const dispatched = await researchRequest;
  expect(dispatched.postDataJSON()).toMatchObject({
    research_authorized: true,
    authorization_basis: 'buyer_action',
    research_plan_id: emulate.ambiguity_exploration.research_plan_id,
  });
  await expect(page.getByText(
    /Approved-source research (?:completed|could not complete)/i,
  )).toBeVisible({ timeout: 40_000 });
  await expect(page.getByTestId('product-shelves')).toHaveCount(0);
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
  await context.close();
});

test('chat-pasted official URL and specifications enter their governed review paths', async ({ browser }) => {
  test.setTimeout(300_000);
  const { context, page } = await openBuyer(browser, 'emulate3d-paste-bridges');
  await send(page, 'I need a laptop for Rockwell Emulate3D PLC digital twin simulation.');

  const sourceResponse = page.waitForResponse(
    response => /\/evidence-source-resolutions$/.test(response.url()),
    { timeout: 90_000 },
  );
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('Official link: https://store.sim3d.com/demo3d_2025/system_requirements');
  await input.press('Enter');
  const sourcePayload = await (await sourceResponse).json();
  expect(sourcePayload.resolution?.status).toBe('resolved');
  expect(sourcePayload.resolution?.selected_source_id).toBe(
    'rockwell_emulate3d_official_requirements',
  );
  expect(sourcePayload.resolution?.candidates?.[0]?.match_basis).toBe('enrolled_domain');

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
  await expect(page.getByTestId('buyer-requirement-review')).toBeVisible();
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
