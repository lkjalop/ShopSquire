import { expect, test, type Browser, type Page } from '@playwright/test';

type NovelTitleCase = {
  name: string;
  query: string;
  canonicalTitle: RegExp;
};

const cases: NovelTitleCase[] = [
  {
    name: 'mio',
    query: 'Is AUD 1,800 enough for a laptop to play MIO Memories in Orbit well?',
    canonicalTitle: /MIO:\s*Memories in Orbit/i,
  },
  {
    name: 'pragmata',
    query: 'Could a laptop under AUD 2,500 run PRAGMATA at 1080p?',
    canonicalTitle: /PRAGMATA/i,
  },
  {
    name: 'dawnwalker',
    query: 'What PC do I need for The Blood of Dawnwalker, and has it released yet?',
    canonicalTitle: /The Blood of Dawnwalker/i,
  },
];

async function openBuyer(browser: Browser, name: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `novel-title-${name}-${Date.now()}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  return { context, page };
}

async function captureTerminal(page: Page, trigger: () => Promise<void>) {
  let finish!: (value: any) => void;
  let fail!: (reason: Error) => void;
  const terminal = new Promise<any>((resolve, reject) => { finish = resolve; fail = reject; });
  const timer = setTimeout(() => fail(new Error('terminal answer timeout')), 180_000);
  const onResponse = async (response: import('@playwright/test').Response) => {
    if (response.request().method() !== 'POST'
      || !/\/api\/v1\/chat\/(?:query|stream)(?:\?|$)/.test(response.url())) return;
    try {
      if (!response.ok()) throw new Error(`chat response ${response.status()}`);
      const body = await response.text();
      const payloads: any[] = [];
      if (!body.includes('data:')) payloads.push(JSON.parse(body));
      else for (const frame of body.replaceAll('\r\n', '\n').split('\n\n')) {
        if (!frame.includes('event: answer')) continue;
        const raw = frame.split('\n').filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).trim()).join('\n');
        if (raw) payloads.push(JSON.parse(raw));
      }
      const completed = payloads.find(item => item?.status !== 'in_progress');
      if (completed) finish(completed);
    } catch (error) {
      fail(error instanceof Error ? error : new Error(String(error)));
    }
  };
  page.on('response', onResponse);
  try {
    await trigger();
    return await terminal;
  } finally {
    clearTimeout(timer);
    page.off('response', onResponse);
  }
}

async function send(page: Page, query: string) {
  return captureTerminal(page, async () => {
    const input = page.getByPlaceholder('Type your message...');
    await input.fill(query);
    await input.press('Enter');
  });
}

test('evidence delivery preserves distinct official values in the rendered review card', async ({ browser }, testInfo) => {
  test.skip(process.env.RUN_LIVE_NOVEL_TITLE_BATTERY !== '1', 'requires live search and Ollama');
  test.setTimeout(240_000);
  const { context, page } = await openBuyer(browser, 'claim-values');
  try {
    const answer = await send(page, 'Would AUD 2500 be enough for a laptop for shapez 2?');
    await testInfo.attach('terminal.json', { body: Buffer.from(JSON.stringify(answer)), contentType: 'application/json' });
    const claims = answer.buyer_requirement_claims || [];
    expect(claims.length).toBeGreaterThanOrEqual(2);
    expect(new Set(claims.map((claim: any) => claim.claim_id)).size).toBe(claims.length);
    for (const attribute of ['ram_gb', 'gpu_vram_gb']) {
      const claim = claims.find((item: any) => item.attribute === attribute);
      expect(claim).toBeDefined();
      expect(claim.authority_status).toBe('verified_official');
      const value = page.getByRole('textbox', { name: `Correct ${attribute.replaceAll('_', ' ')} value`, exact: true });
      await expect(value).toHaveValue(String(claim.value));
      await expect(value).toHaveAttribute('readonly', '');
    }
    expect(answer.terminal_outcome.case_revision).toBe(answer.case_revision);
    expect(answer.terminal_outcome.operation_id).toBe(answer.operation_id);
    expect(answer.terminal_outcome.catalog_authority).toBe('permitted');
    const terminal = answer.terminal_outcome;
    const products = [...(terminal.products || []), ...(terminal.product_shelves?.shelves || []).flatMap((s: any) => s.initial || [])];
    expect(products.length).toBeGreaterThan(0);
    await expect(page.getByText(/These came from your upload/)).toHaveCount(0);
  } finally { await context.close(); }
});

test('evidence delivery never binds FreeCAD to AutoCAD requirements', async ({ browser }, testInfo) => {
  test.skip(process.env.RUN_LIVE_NOVEL_TITLE_BATTERY !== '1', 'requires live search and Ollama');
  test.setTimeout(240_000);
  const { context, page } = await openBuyer(browser, 'source-applicability');
  try {
    const answer = await send(page, 'I work in FreeCAD on large assemblies. What computer would suit under AUD 3500?');
    await testInfo.attach('terminal.json', { body: Buffer.from(JSON.stringify(answer)), contentType: 'application/json' });
    const applied = JSON.stringify({
      claims: answer.buyer_requirement_claims,
      identity: answer.terminal_outcome?.research_outcome?.identity,
      requirements: answer.workload_authorization?.evidence,
    });
    expect(applied).not.toMatch(/autocad|autodesk_autocad_requirements/i);
    expect(answer.terminal_outcome.case_revision).toBe(answer.case_revision);
    expect(answer.assistant_message).not.toMatch(/AutoCAD/i);
    const terminal = answer.terminal_outcome;
    if (terminal.catalog_authority === 'blocked') {
      expect(terminal.recommendation_status).toBe('blocked');
      expect(terminal.products).toEqual([]);
      expect(terminal.product_shelves).toBeNull();
    }
  } finally { await context.close(); }
});

for (const scenario of cases) {
  test(`unseen title ${scenario.name} resolves without an application alias`, async ({ browser }, testInfo) => {
    test.skip(process.env.RUN_LIVE_NOVEL_TITLE_BATTERY !== '1', 'requires demo-live search and Ollama');
    test.setTimeout(300_000);
    const { context, page } = await openBuyer(browser, scenario.name);
    const answer = await send(page, scenario.query);
    await testInfo.attach(`${scenario.name}.json`, {
      body: Buffer.from(JSON.stringify(answer, null, 2)),
      contentType: 'application/json',
    });

    const outcome = answer.terminal_outcome?.research_outcome;
    expect(answer.terminal_outcome?.execution_evidence?.core_invocation_count).toBe(1);
    expect(answer.terminal_outcome?.case_revision).toBe(answer.case_revision);
    expect(outcome?.case_revision).toBe(answer.case_revision);
    expect(outcome?.identity?.title || '').toMatch(scenario.canonicalTitle);
    expect(outcome?.discovery_status).toBe('completed');
    expect(outcome?.requirement_completeness).not.toBe('none');
    expect(
      (outcome?.parsed_claim_count || 0)
      + (outcome?.accepted_claim_count || 0)
      + (answer.workload_authorization?.evidence?.length || 0),
    ).toBeGreaterThan(0);

    const terminalText = JSON.stringify(answer.terminal_outcome || {});
    expect(terminalText).toMatch(scenario.canonicalTitle);
    expect(answer.assistant_message || '').toMatch(scenario.canonicalTitle);
    expect(answer.assistant_message || '').not.toMatch(/general (office|gaming)|which level fits/i);
    if (scenario.name === 'pragmata') {
      expect(outcome?.accepted_claim_count || 0).toBeGreaterThan(0);
      const shelves = answer.terminal_outcome?.product_shelves?.shelves
        || answer.product_shelves?.shelves || [];
      const shelfProducts = shelves.flatMap((shelf: any) => [
        ...(shelf?.initial || []), ...(shelf?.next_page || []),
      ]);
      expect(answer.terminal_outcome?.catalog_authority).toBe('permitted');
      expect(shelfProducts.length).toBeGreaterThan(0);
      expect(answer.assistant_message || '').not.toMatch(
        /could not obtain approved current requirements|which named software/i,
      );
    }

    await page.getByTitle('Decision Trace').click();
    const trace = page.getByTestId('decision-trace-modal');
    for (const tab of [
      'Decision', 'Research & Fit', 'Reasoning', 'Evidence & Risk',
      'Commercial Journey', 'Advanced technical details',
    ]) {
      await trace.getByRole('button', { name: new RegExp(`^${tab}`) }).click();
      await expect(trace).toBeVisible();
      await expect(trace).not.toContainText(/404|not found/i);
    }
    await trace.getByRole('button', { name: /^Research & Fit/ }).click();
    await expect(trace).toContainText(scenario.canonicalTitle);
    await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
    await context.close();
  });
}

test('non-instructive continuation resolves its clean subject span', async ({ browser }, testInfo) => {
  test.skip(process.env.RUN_LIVE_NOVEL_TITLE_BATTERY !== '1', 'requires demo-live search and Ollama');
  test.setTimeout(300_000);
  const { context, page } = await openBuyer(browser, 'where-winds-meet-continuation');
  await send(page, 'gaming laptop under 3000');
  const answer = await send(page, 'what about for where winds meet is 3000 ok?');
  await testInfo.attach('where-winds-meet-continuation.json', {
    body: Buffer.from(JSON.stringify(answer, null, 2)),
    contentType: 'application/json',
  });

  const outcome = answer.terminal_outcome?.research_outcome;
  expect(outcome?.identity?.title || '').toMatch(/^Where Winds Meet$/i);
  expect(outcome?.accepted_claim_count || 0).toBeGreaterThan(0);
  expect(answer.terminal_outcome?.catalog_authority).toBe('permitted');
  const shelves = answer.terminal_outcome?.product_shelves?.shelves
    || answer.product_shelves?.shelves || [];
  expect(shelves.flatMap((shelf: any) => [
    ...(shelf?.initial || []), ...(shelf?.next_page || []),
  ]).length).toBeGreaterThan(0);
  expect(answer.assistant_message || '').not.toMatch(
    /found 0 candidate|which named software|general gaming/i,
  );
  expect(answer.commercial_terms?.quantity).toBeFalsy();
  expect(answer.action_executed).not.toBe(true);
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
  await context.close();
});

test('low-confidence cited identity asks for confirmation without fetching', async ({ browser }, testInfo) => {
  test.skip(process.env.RUN_LIVE_NOVEL_TITLE_BATTERY !== '1', 'requires demo-live search and Ollama');
  test.setTimeout(300_000);
  const { context, page } = await openBuyer(browser, 'low-confidence-dawnwalker');
  const answer = await send(
    page, 'What laptop for bloodwalker the new witcher under AUD 3,000?',
  );
  await testInfo.attach('low-confidence-dawnwalker.json', {
    body: Buffer.from(JSON.stringify(answer, null, 2)),
    contentType: 'application/json',
  });

  const outcome = answer.terminal_outcome?.research_outcome;
  expect(answer.terminal_outcome?.execution_evidence?.core_invocation_count).toBe(1);
  expect(outcome?.identity?.title || '').toMatch(/^The Blood of Dawnwalker$/i);
  expect(outcome?.failure_code).toBe('low_confidence_identity_confirmation_required');
  expect(outcome?.fetch_status).toBe('not_attempted');
  expect(answer.terminal_outcome?.catalog_authority).not.toBe('permitted');
  expect(answer.assistant_message || '').toMatch(/Did you mean The Blood of Dawnwalker/i);
  expect(JSON.stringify(answer.terminal_outcome?.next_questions || [])).toMatch(
    /Did you mean The Blood of Dawnwalker/i,
  );
  const shelves = answer.terminal_outcome?.product_shelves?.shelves || [];
  expect(shelves.flatMap((shelf: any) => [
    ...(shelf?.initial || []), ...(shelf?.next_page || []),
  ])).toHaveLength(0);
  const confirmation = page.getByTestId('canonical-identity-confirmation');
  await expect(confirmation).toBeVisible();
  const confirmed = await captureTerminal(page, async () => {
    await page.getByTestId('confirm-canonical-identity-yes').click();
  });
  expect(confirmed.case_revision).toBeGreaterThan(answer.case_revision);
  expect(confirmed.terminal_outcome?.research_outcome?.identity?.title || '').toMatch(
    /^The Blood of Dawnwalker$/i,
  );
  expect(JSON.stringify(confirmed.terminal_outcome || {})).not.toMatch(/bloodwalker the new witcher/i);
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
  await context.close();
});
