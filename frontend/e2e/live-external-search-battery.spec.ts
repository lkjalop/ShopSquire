import { expect, test, type Browser, type Page } from '@playwright/test';

async function openBuyer(browser: Browser, name: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.addInitScript((uid) => {
    localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem('uid', uid);
  }, `external-battery-${name}-${Date.now()}`);
  await page.goto('/');
  // The floating launcher has a continuous attention animation in demo-live.
  // Playwright's default actionability waits for geometrical stability, which
  // can never become true for an intentionally animated control.
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  return { context, page };
}

async function send(page: Page, query: string) {
  const responsePromise = page.waitForResponse(response => (
    response.request().method() === 'POST'
      && /\/api\/v1\/chat\/(?:query|stream)(?:\?|$)/.test(response.url())
  ), { timeout: 150_000 });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(query); await input.press('Enter');
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();
  const body = await response.text();
  if (!body.includes('data:')) return JSON.parse(body);
  for (const frame of body.replaceAll('\r\n', '\n').split('\n\n').reverse()) {
    if (!frame.includes('event: answer')) continue;
    const raw = frame.split('\n').filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trim()).join('\n');
    if (raw) return JSON.parse(raw);
  }
  throw new Error(`missing terminal answer: ${body.slice(0, 800)}`);
}

function assertOneTruth(answer: any) {
  expect(answer.terminal_outcome?.case_id).toBe(answer.shopping_case_id);
  expect(answer.terminal_outcome?.case_revision).toBe(answer.case_revision);
  expect(answer.terminal_outcome?.decision_trace_id).toBe(answer.decision_trace_id);
  expect(answer.terminal_outcome?.execution_evidence?.core_invocation_count).toBe(1);
  expect(answer.terminal_outcome?.commerce_authority).toBe('none');
  if (answer.terminal_outcome?.research_outcome) {
    expect(answer.terminal_outcome.research_outcome.case_id)
      .toBe(answer.terminal_outcome.case_id);
    expect(answer.terminal_outcome.research_outcome.case_revision)
      .toBe(answer.terminal_outcome.case_revision);
    if (answer.server_research_result?.research_outcome) {
      expect(answer.server_research_result.research_outcome.case_id)
        .toBe(answer.terminal_outcome.case_id);
      expect(answer.server_research_result.research_outcome.case_revision)
        .toBe(answer.terminal_outcome.case_revision);
    }
  }
}

async function assertTraceTabs(page: Page) {
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
}

test('A-H live external intelligence battery is revision-bound and fail-closed', async ({ browser }, testInfo) => {
  test.skip(process.env.RUN_LIVE_EXTERNAL_BATTERY !== '1', 'requires demo-live search and Ollama');
  test.setTimeout(900_000);

  const allScenarios = [
    ['A', 'I need a gaming laptop under AUD 3,000.', 'What about Where Winds Meet? Has it been released?'],
    ['B', "Is AUD 3,000 excessive for Baldur's Gate 3?", 'What about Rockwell Emulate3D running locally?'],
    ['C', null, 'I process large drone surveys in Agisoft Metashape. What hardware do I need under AUD 4,000?'],
    ['D', null, 'I need hardware for CupixWorks. Inspect https://www.cupix.com/home-1?utm_source=google&utm_medium=cpc&gclid=secret-demo'],
    ['E', null, 'I need a laptop for tarae. Find out what that title is before recommending anything.'],
    ['F', null, 'I need a computer for digital twin simulation; compare desktop and mobile workstation options.'],
    ['G', null, 'I have AUD 2,500 for Bloodwalker. Is it released and what is the nearest requirements equivalent?'],
    ['H', null, 'I need a workstation that can run Factory IO locally.'],
  ] as const;
  const requested = new Set(String(process.env.BATTERY_SCENARIOS || 'ABCDEFGH').split(''));
  const scenarios = allScenarios.filter(([name]) => requested.has(name));

  for (const [name, first, last] of scenarios) {
    const { context, page } = await openBuyer(browser, name);
    if (first) await send(page, first);
    const answer = await send(page, last);
    await testInfo.attach(`scenario-${name}.json`, {
      body: Buffer.from(JSON.stringify(answer, null, 2)), contentType: 'application/json',
    });
    console.log(JSON.stringify({
      scenario: name,
      operation_id: answer.operation_id,
      case_revision: answer.case_revision,
      canonical_budget: answer.canonical_budget,
      subject_role: answer.subject_role,
      subject_role_status: answer.subject_role_status,
      identity_status: answer.server_research_result?.research?.identity_resolution?.status,
      identity_failure: answer.server_research_result?.research?.identity_resolution?.failure_code,
      identity_latency_ms: answer.server_research_result?.research?.identity_resolution?.latency_ms,
      identity: answer.server_research_result?.research?.identity_resolution?.identity,
      auto_fetch_status: answer.server_research_result?.research?.official_origin_auto_fetch?.research_status,
      auto_fetch_claim_count: answer.server_research_result?.research?.official_origin_auto_fetch?.claims?.length || 0,
      research_outcome: answer.server_research_result?.research_outcome,
    }));
    assertOneTruth(answer);
    expect(JSON.stringify(answer)).not.toContain('RuntimeError');
    if (name === 'A') {
      expect(answer.workload_authorization?.evidence?.[0]?.canonical_title).toBe('Where Winds Meet');
      expect(answer.workload_authorization?.evidence?.[0]?.release_state).toBeTruthy();
    }
    if (name === 'B') {
      expect(JSON.stringify(answer.case_memory?.read_model || {})).not.toMatch(/Baldur'?s Gate 3/i);
      expect(JSON.stringify(answer)).toMatch(/Rockwell Emulate3D/i);
      expect(answer.canonical_budget?.budget_max).toBe(3000);
      expect(answer.turn_read_model?.canonical_budget?.budget_max).toBe(3000);
    }
    if (name === 'C') {
      const result = answer.server_research_result;
      expect(result?.research?.identity_resolution?.identity?.canonical_title || '')
        .toMatch(/Agisoft Metashape/i);
      expect(result?.research?.official_origin_auto_fetch_policy?.authorized).toBe(true);
      expect(result?.research_outcome?.held_claim_count || 0).toBeGreaterThan(0);
    }
    if (name === 'D') {
      expect(JSON.stringify(answer)).not.toContain('secret-demo');
      expect(answer.buyer_evidence_source_resolution?.resolution?.link_assessment
        ?.tracking_parameters_removed || 0).toBeGreaterThan(0);
      expect(answer.server_research_result?.research?.provider_accounting?.external_calls || 0)
        .toBeGreaterThan(0);
    }
    if (name === 'E') {
      if (answer.server_research_result?.research?.identity_resolution?.status !== 'resolved') {
        expect(answer.products || []).toHaveLength(0);
      }
    }
    if (name === 'F') {
      const labels = (answer.server_research_result?.product_shelves?.shelves || [])
        .map((row: any) => String(row.scope_label || '')).join(' ');
      expect(labels || JSON.stringify(answer.architecture_alternatives || {}))
        .toMatch(/desktop|fixed workstation/i);
      expect(labels || JSON.stringify(answer.architecture_alternatives || {}))
        .toMatch(/mobile workstation|laptop/i);
    }
    if (name === 'G') {
      expect(answer.canonical_budget?.budget_max).toBe(2500);
      expect(answer.turn_read_model?.canonical_budget?.budget_max).toBe(2500);
      expect(answer.terminal_outcome?.canonical_facts?.canonical_budget?.budget_max).toBe(2500);
    }
    if (name === 'H') {
      expect(JSON.stringify(answer)).toMatch(/Factory I\/O|Factory IO/i);
      expect(JSON.stringify(answer)).not.toMatch(/Factory App|factory\.ai/i);
    }
    await assertTraceTabs(page);
    await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
    await context.close();
  }
});
