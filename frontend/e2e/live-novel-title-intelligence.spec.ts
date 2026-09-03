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

async function send(page: Page, query: string) {
  const responsePromise = page.waitForResponse(response => (
    response.request().method() === 'POST'
      && /\/api\/v1\/chat\/(?:query|stream)(?:\?|$)/.test(response.url())
  ), { timeout: 180_000 });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(query);
  await input.press('Enter');
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
