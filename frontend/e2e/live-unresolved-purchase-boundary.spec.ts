import { expect, test, type Page } from '@playwright/test';

test.describe.configure({ retries: 0 });

test('approximate budget keeps its literal anchor without automatic stretch', async ({ page }, info) => {
  test.setTimeout(180_000);
  await page.addInitScript(uid => { sessionStorage.setItem('uid', uid); }, `approx-budget-${Date.now()}`);
  await page.goto('/');
  await page.getByRole('button', { name: 'Ask Me!', exact: true }).click();
  const response = await send(page, 'I need a laptop for about AUD 3000');
  const terminal = response.terminal_outcome;
  const budget = terminal.canonical_facts.canonical_budget;
  await info.attach('budget-contract', { body: JSON.stringify({ budget, panel: terminal.right_panel?.canonical_budget, operation_id: terminal.operation_id }), contentType: 'application/json' });
  expect(budget).toMatchObject({ mode: 'around', budget_min: null, budget_max: 3000 });
  expect(terminal.right_panel.canonical_budget).toEqual(budget);
  for (const shelf of terminal.product_shelves?.shelves || []) {
    expect(shelf.budget_band).not.toBe('stretch');
    for (const product of [...(shelf.initial || []), ...(shelf.remaining || [])]) expect(product.price_cents).toBeLessThanOrEqual(300000);
  }
  await expect(page.getByText('budget AUD 3,600', { exact: false })).toHaveCount(0);
  const continued = await send(page, 'It needs more storage');
  expect(continued.terminal_outcome.canonical_facts.canonical_budget).toMatchObject({
    mode: 'around', budget_min: null, budget_max: 3000,
  });
  expect(continued.terminal_outcome.right_panel.canonical_budget)
    .toEqual(continued.terminal_outcome.canonical_facts.canonical_budget);
});

async function send(page: Page, query: string) {
  const result = new Promise<any>((resolve, reject) => {
    const timer = setTimeout(() => { page.off('response', handler); reject(new Error('terminal deadline')); }, 150_000);
    const handler = async (response: any) => {
      if (!/\/chat\/(query|stream)|\/operations\//.test(response.url())) return;
      try {
        const text = await response.text();
        const rows = text.startsWith('{') ? [JSON.parse(text)] : text.replaceAll('\r\n', '\n')
          .split('\n\n').filter((row: string) => row.includes('event: answer'))
          .map((row: string) => JSON.parse(row.split('\n').find(line => line.startsWith('data: '))!.slice(6)));
        for (const row of rows) if (row.terminal_outcome?.operation_id) {
          clearTimeout(timer); page.off('response', handler); resolve(row);
        }
      } catch { /* Progress is not a terminal result. */ }
    };
    page.on('response', handler);
  });
  await page.getByPlaceholder('Type your message...').fill(query);
  await page.getByPlaceholder('Type your message...').press('Enter');
  return result;
}

test('held workload cannot answer a new unresolved purchase', async ({ page }, info) => {
  test.setTimeout(330_000);
  const mutations: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /confirm-cart|send-approved|send-autonomous|payments/.test(request.url())) mutations.push(request.url());
  });
  await page.addInitScript(uid => { sessionStorage.setItem('uid', uid); }, `held-boundary-${Date.now()}`);
  await page.goto('/');
  await page.getByRole('button', { name: 'Ask Me!', exact: true }).click();
  const first = await send(page, 'I need a laptop under AUD 3000 that can run Rockwell Emulate3D locally');
  expect(first.terminal_outcome.research_outcome.held_claim_count).toBeGreaterThan(0);
  const second = await send(page, 'actually i need something with better disaster recovery like a raid 5? what else to buy?');
  const terminal = second.terminal_outcome;
  await info.attach('boundary-outcomes', { body: JSON.stringify({ first: first.terminal_outcome, second: terminal }), contentType: 'application/json' });
  expect(terminal.operation_id).not.toBe(first.terminal_outcome.operation_id);
  expect(terminal.catalog_scope.selected_taxonomy_root).not.toBe('el-6-6');
  expect(terminal.research_outcome?.held_claim_count || 0).toBe(0);
  expect(terminal.products).toEqual([]);
  expect(terminal.assistant_message).not.toMatch(/16 cited|simulation, rendering|gaming level/i);
  expect(JSON.stringify(terminal.next_questions)).not.toMatch(/named software|simulation, rendering/i);
  expect(terminal.right_panel.canonical_budget).toEqual(terminal.canonical_facts.canonical_budget);
  expect(terminal.canonical_facts.canonical_budget.budget_max).toBe(3000);
  expect(second.turn_read_model.operation_id).toBe(terminal.operation_id);
  expect(second.turn_read_model.case_revision).toBe(terminal.case_revision);
  expect(terminal.commerce_authority).toBe('none');
  expect(mutations).toEqual([]);
  await expect(page.getByText('Held for review', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Retry approved research', exact: true })).toHaveCount(0);
  await page.getByTitle('Decision Trace', { exact: true }).click();
  await expect(page.getByTestId('decision-trace-modal')).toContainText(`Case revision ${terminal.case_revision}`);
});
