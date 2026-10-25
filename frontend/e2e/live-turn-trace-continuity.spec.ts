import { expect, test, type Page, type Response } from '@playwright/test';
import { registerBuyer } from './helpers/registeredBuyer';
import { turnViolations } from './helpers/turnOracle';

const sections = {
  'Decision': ['summary', 'events', 'execution'],
  'Research & Fit': ['research', 'why'],
  'Reasoning': ['intent', 'memory', 'complexity'],
  'Evidence & Risk': ['evidence', 'multimodal', 'security'],
  'Commercial Journey': ['market', 'procurement'],
  'Advanced technical details': ['audit', 'raw'],
};

async function send(page: Page, query: string): Promise<any> {
  let handler: (response: Response) => Promise<void>;
  let timer: ReturnType<typeof setTimeout>;
  const answer = new Promise<any>((resolve, reject) => {
    timer = setTimeout(() => reject(new Error('No terminal turn outcome')), 180_000);
    handler = async response => {
      if (!/\/chat\/(query|stream)|\/operations\//.test(response.url())) return;
      try {
        const text = await response.text();
        const rows = text.startsWith('{') ? [JSON.parse(text)] : text.replaceAll('\r\n', '\n')
          .split('\n\n').filter(row => row.includes('event: answer'))
          .map(row => JSON.parse(row.split('\n').find(line => line.startsWith('data: '))!.slice(6)));
        for (const row of rows) if (row.terminal_outcome) resolve(row);
      } catch { /* Non-terminal progress frames carry no recommendation authority. */ }
    };
    page.on('response', handler);
  });
  try {
    await page.getByPlaceholder('Type your message...').fill(query);
    await page.getByPlaceholder('Type your message...').press('Enter');
    return await answer;
  } finally { clearTimeout(timer!); page.off('response', handler!); }
}

test('screenshot price correction never becomes a bulk order', async ({page}, info) => {
  test.setTimeout(540_000);
  await expect.poll(async () => {
    try { return (await page.request.get(`${process.env.PLAYWRIGHT_API_URL || 'http://127.0.0.1:8080'}/healthz`, {timeout:3000})).status(); }
    catch { return 0; }
  }, {timeout:60_000}).toBe(200);
  await registerBuyer(page.context());
  await page.goto('/');
  await page.getByRole('button', {name:/Ask Me/i}).click({force:true});
  for (const query of ['need help with a 2000 laptop for digital twin?',
    'i mean a $2000 laptop?', 'per item?']) {
    const data = await send(page, query);
    const terminal = data.terminal_outcome;
    await info.attach(`price-${terminal.operation_id}`, {
      body: JSON.stringify(data, null, 2), contentType:'application/json',
    });
    expect(turnViolations(data, {buyerQuery:query, budgetMax:2000})).toEqual([]);
    expect(data.decision.quantity ?? 1).toBe(1);
    expect(terminal.assistant_message).not.toMatch(/2000 units|2,000 units|1,258,000|4,000,000|all 2000/);
    expect(terminal.ambiguity_exploration?.retained_purpose).toMatch(/digital twin/i);
    expect(terminal.assistant_message).not.toMatch(/ample for general|strong fits start|good news/i);
    expect(terminal.assistant_message).toMatch(/cannot confirm.*(?:compatibility|budget)/i);
    await expect(page.getByText(terminal.assistant_message, {exact:true}).last()).toBeVisible();
    expect(terminal.right_panel?.bulk_budget?.quantity ?? 1).toBe(1);
    await expect(page.getByText(/Fulfilment options for your bulk order/i)).not.toBeVisible();
    expect(terminal.commerce_authority).toBe('none');
    await page.getByTitle('Decision Trace', {exact:true}).click();
    const trace = page.getByTestId('decision-trace-modal');
    await expect(trace.getByTestId('revision-bound-turn-projection'))
      .toContainText(`Case revision ${terminal.case_revision}`);
    await expect(trace.getByTestId('revision-bound-research-outcome'))
      .toContainText(`${terminal.research_outcome.accepted_claim_count} accepted, ${terminal.research_outcome.held_claim_count} held`);
    await trace.getByTitle('Close', {exact:true}).click();
  }
  const changed = await send(page, 'Actually I need a computer chair under AUD 400, not a laptop.');
  expect(changed.terminal_outcome.assistant_message).not.toMatch(/software and local workload|workload context/i);
  expect(changed.terminal_outcome.assistant_message).toMatch(/chair/i);
  expect(turnViolations(changed, {budgetMax:400})).toEqual([]);
});

test('genuine bulk purchase retains quantity with readable currency narration', async ({page}, info) => {
  test.setTimeout(240_000);
  await registerBuyer(page.context());
  await page.goto('/');
  await page.getByRole('button', {name:/Ask Me/i}).click({force:true});
  const data = await send(page, 'I need 50 laptops with a total budget of AUD 60,000.');
  const terminal = data.terminal_outcome;
  await info.attach('genuine-bulk', {body:JSON.stringify(data,null,2),contentType:'application/json'});
  expect(turnViolations(data, {budgetMax:60000})).toEqual([]);
  expect(data.decision.quantity).toBe(50);
  expect(terminal.assistant_message).toMatch(/50 units/);
  expect(terminal.assistant_message).not.toMatch(/for general\b|\$[\d,]+\.\d(?!\d)/);
  await expect(page.getByText(terminal.assistant_message, {exact:true}).last()).toBeVisible();
  expect(terminal.commerce_authority).toBe('none');
});

test('live category and quantity turns retain their own trace and recorded history', async ({ page }, info) => {
  test.setTimeout(540_000);
  // A restarted API must be reachable before the storefront takes its initial
  // catalog snapshot. Readiness polling is not a retry of a buyer turn.
  await expect.poll(async () => {
    try {
      return (await page.request.get(`${process.env.PLAYWRIGHT_API_URL || 'http://127.0.0.1:8080'}/healthz`,
        {timeout: 3000})).status();
    } catch { return 0; }
  }, {timeout: 60_000, message: 'API must be reachable before the live journey'}).toBe(200);
  const dispatches: string[] = [];
  const failures: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /confirm-cart|send-approved|send-autonomous/.test(request.url())) dispatches.push(request.url());
  });
  page.on('response', response => {
    if (response.url().includes('/api/') && response.status() >= 400) failures.push(`${response.status()} ${response.url()}`);
  });
  await registerBuyer(page.context());
  await page.goto('/');
  await page.getByRole('button', {name:/Ask Me/i}).click({force:true});
  const operations = new Set<string>();
  const traces = new Set<string>();
  let previousTerminal: any;
  for (const query of [
    'Could a laptop under AUD 2,500 run PRAGMATA at 1080p?',
    'Actually I need a computer chair under AUD 400, not a laptop.',
    'Now I need 10 laptops with a total budget of AUD 30,000.',
    'Make that 12 laptops, keeping the total budget at AUD 30,000.',
  ]) {
    const data = await send(page, query);
    const terminal = data.terminal_outcome;
    expect(turnViolations(data, {
      buyerQuery: query,
      budgetMax: [2500, 400, 30000, 30000][operations.size],
      ...(operations.size === 1 ? {
        forbiddenQuestionGoals: ['resolve_budget_capability_gap', 'resolve_named_workload'],
      } : {}),
      ...(operations.size >= 2 ? {taxonomyRoots:['el-6-6', 'el-6-11-2']} : {}),
    })).toEqual([]);
    if (operations.size === 1) {
      expect(terminal.catalog_scope?.selected_taxonomy_root || '')
        .not.toMatch(/^el-/);
      expect(terminal.product_shelves?.shelves || []).toEqual([]);
    }
    if (operations.size >= 2) {
      const cards = terminal.product_shelves
        ? (terminal.product_shelves.shelves || []).flatMap((s:any) =>
          [...(s.initial || []), ...(s.remaining || [])])
        : (terminal.products || []);
      expect(cards.length, 'Plain bulk laptop requests must deliver the available catalog slate').toBeGreaterThan(0);
      expect(data.decision.requested_product_node).toBe(terminal.catalog_scope.selected_taxonomy_root);
      await expect(page.getByText(cards[0].title || cards[0].name, {exact:true}).last()).toBeVisible();
      expect(terminal.slate_disposition).toBe('replace');
      expect(terminal.catalog_authority).not.toBe('blocked');
      if (terminal.right_panel?.bulk_budget?.stock_freshness_status !== 'fresh') {
        expect(terminal.assistant_message).toContain('current stock and transfer availability are not verified');
        expect(terminal.assistant_message).not.toMatch(/units are available across the network|location now|can transfer/);
      }
      expect(terminal.next_questions || []).not.toEqual(expect.arrayContaining([
        expect.objectContaining({id:'priority_tradeoff'}),
      ]));
    }
    expect(terminal.operation_id).toBeTruthy();
    expect(operations.has(terminal.operation_id)).toBe(false);
    operations.add(terminal.operation_id);
    expect(terminal.decision_trace_id).toBeTruthy();
    expect(traces.has(terminal.decision_trace_id)).toBe(false);
    traces.add(terminal.decision_trace_id);
    expect(data.turn_read_model.operation_id).toBe(terminal.operation_id);
    expect(data.turn_read_model.case_revision).toBe(terminal.case_revision);
    expect(terminal.commerce_authority).toBe('none');
    if (operations.size === 4) {
      expect(terminal.case_id).toBe(previousTerminal.case_id);
      expect(terminal.case_revision).toBe(previousTerminal.case_revision + 1);
    }
    await page.getByTitle('Decision Trace', {exact:true}).click();
    const modal = page.getByTestId('decision-trace-modal');
    await expect(modal).toBeVisible();
    if (operations.size === 1) {
      expect(terminal.research_outcome).toBeTruthy();
      const outcome = terminal.research_outcome;
      await expect(modal.getByTestId('revision-bound-research-outcome'))
        .toContainText(`${outcome.accepted_claim_count} accepted, ${outcome.held_claim_count} held`);
      await expect(modal.getByTestId('revision-bound-turn-projection'))
        .toContainText(`Case revision ${terminal.case_revision}`);
    }
    const panels: Record<string, string> = {};
    for (const [section, leaves] of Object.entries(sections)) {
      await modal.getByLabel('Decision Trace sections', {exact:true}).getByRole('button', {name:new RegExp('^'+section)}).click();
      const reveal = modal.getByRole('button', {name:'Show empty panels', exact:true});
      if (await reveal.isVisible()) await reveal.click();
      for (const leaf of leaves) {
        await modal.getByTestId('trace-leaf-'+leaf).click();
        const panel = modal.getByRole('tabpanel');
        await expect(panel).not.toContainText(/Loading .*?(?:\.{3}|…)/i, {timeout:20_000});
        const procurementState = panel.getByTestId('procurement-load-state');
        if (await procurementState.count()) {
          await expect(procurementState).toHaveAttribute('data-state', /^(ready|not_applicable)$/);
          await expect(procurementState).toHaveAttribute('aria-busy', 'false');
        }
        await expect(panel).not.toBeEmpty();
        panels[leaf] = await panel.innerText();
        if (leaf === 'research' && operations.size === 1) {
          const outcome = terminal.research_outcome;
          const summary = panel.getByTestId('research-outcome-summary');
          await expect(summary).toBeVisible();
          for (const [label, value] of Object.entries({Parsed:outcome.parsed_claim_count,
            Held:outcome.held_claim_count, Accepted:outcome.accepted_claim_count,
            Rejected:outcome.rejected_claim_count})) {
            await expect(summary).toContainText(`${label}: ${value}`);
          }
          await expect(summary).toContainText(`Catalog authority: ${outcome.catalog_authority.replaceAll('_', ' ')}`);
        }
        if (leaf === 'summary') {
          await expect(panel).toContainText(terminal.decision_trace_id);
          await expect(panel).toContainText(query);
        }
        if (leaf === 'audit') await expect(panel.getByTestId('recorded-turn-history')).toBeVisible();
        if (leaf === 'audit' && operations.size === 4) {
          const history = panel.getByTestId('recorded-turn-history');
          await history.getByLabel('Recorded turn revision').selectOption({label:`Revision ${previousTerminal.case_revision}`});
          await expect(history).toContainText(previousTerminal.operation_id);
          await expect(history).not.toContainText(terminal.operation_id);
          await history.getByLabel('Recorded turn revision').selectOption({label:`Revision ${terminal.case_revision}`});
          await expect(history).toContainText(terminal.operation_id);
          await expect(history).toContainText('commerce authority: none');
        }
      }
    }
    expect(panels.raw).toContain(terminal.decision_trace_id);
    await info.attach(`turn-${operations.size}`, {body:JSON.stringify({terminal,panels}, null, 2), contentType:'application/json'});
    await modal.getByTitle('Close', {exact:true}).click();
    previousTerminal = terminal;
  }
  expect(dispatches).toEqual([]);
  expect(failures).toEqual([]);
});
