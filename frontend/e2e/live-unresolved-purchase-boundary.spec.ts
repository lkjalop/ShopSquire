import { expect, test } from './helpers/authenticatedTest';
import { terminalTurn as send } from './helpers/terminalTurn';

test.describe.configure({ retries: 0 });

test.beforeEach(async ({ context }) => {
  const tenant = process.env.VITE_STOREFRONT_TENANT_ID;
  await context.setExtraHTTPHeaders(tenant ? { 'x-tenant-id': tenant } : {});
});

test('KCD2 partial evidence agrees across chat, questions and persisted turn', async ({ page }, info) => {
  test.setTimeout(180_000);
  await page.goto('/');
  await page.getByRole('button', { name: 'Ask Me!', exact: true }).click();
  const response = await send(page, 'What laptop do I need for Kingdom Come Deliverance 2, under AUD 3,000?');
  const terminal = response.terminal_outcome;
  const outcome = terminal.research_outcome;
  expect(outcome.accepted_claim_count).toBeGreaterThan(0);
  expect(outcome.requirement_completeness).toBe('partial');
  expect(outcome.catalog_authority).toBe('blocked');
  expect(terminal.assistant_message).toContain('coverage remains partial');
  expect(terminal.assistant_message).not.toMatch(/qualified\s+\d|qualifies\s+[1-9]/i);
  expect(response.turn_read_model.assistant_message).toBe(terminal.assistant_message);
  expect(response.turn_read_model.catalog_authority).toBe(outcome.catalog_authority);
  const qualified = (terminal.product_shelves?.shelves || []).flatMap((s: any) => [...s.initial, ...(s.next_page || [])])
    .filter((item: any) => item.fit_status === 'qualified');
  expect(qualified).toHaveLength(0);
  expect(terminal.next_questions.some((q: any) => q.reason === 'named_workload_evidence_unresolved')).toBe(false);
  expect(terminal.next_questions.some((q: any) => q.obligation_ids?.includes('requirement:os'))).toBe(true);
  await expect(page.getByText(terminal.assistant_message, { exact: true }).first()).toBeVisible();
  await info.attach('kcd-terminal-truth', { body: JSON.stringify({ terminal, readModel: response.turn_read_model }), contentType: 'application/json' });
});

test('live preflight cannot replace executed provider requirements', async ({ page }, info) => {
  test.setTimeout(180_000);
  await page.goto('/');
  await page.getByRole('button', { name: 'Ask Me!', exact: true }).click();
  const response = await send(page, 'I need a laptop under AUD 5000 to play Baldur’s Gate 3');
  const evidence = response.workload_authorization.evidence;
  const provider = evidence.find((item: any) => item.app_id === '1086940');
  expect(provider).toBeDefined();
  expect(provider.fetch_receipt.execution_status).toBe(provider.cached ? 'cached' : 'completed');
  expect(provider.live_allowed).toBe(true);
  const attributes = provider.compiled_requirements.map((claim: any) => claim.attribute_key);
  expect(attributes).toEqual(expect.arrayContaining(['cpu_model', 'gpu_model']));
  const terminal = response.terminal_outcome;
  expect(terminal.operation_id).toBe(response.operation_id);
  expect(terminal.case_revision).toBe(response.case_revision);
  expect(terminal.research_outcome.accepted_claim_count).toBeGreaterThan(2);
  await info.attach('preflight-reconciliation', { body: JSON.stringify({ provider, outcome: terminal.research_outcome }), contentType: 'application/json' });
});

test('live complete-evidence qualified-product delivery gate', async ({ page }, info) => {
  test.setTimeout(180_000);
  await page.goto('/');
  await page.getByRole('button', { name: 'Ask Me!', exact: true }).click();
  const response = await send(page, 'I need a laptop under AUD 5000 to play Baldur’s Gate 3');
  const terminal = response.terminal_outcome;
  await info.attach('positive-delivery-outcome', { body: JSON.stringify(terminal), contentType: 'application/json' });
  expect(terminal.research_outcome.accepted_claim_count).toBeGreaterThan(0);
  expect(terminal.research_outcome.requirement_completeness).toBe('complete');
  expect(terminal.research_outcome.catalog_authority).toBe('permitted');
  const qualified = (terminal.product_shelves?.shelves || []).flatMap((shelf: any) => [...shelf.initial, ...(shelf.next_page || [])])
    .filter((item: any) => item.fit_status === 'qualified');
  expect(qualified.length, 'Live evidence and matching inventory must actually deliver qualified products').toBeGreaterThan(0);
  await expect(page.getByText(qualified[0].title, { exact: true }).first()).toBeVisible();
});

test('approximate budget keeps its literal anchor without automatic stretch', async ({ page }, info) => {
  test.setTimeout(180_000);
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


test('held workload cannot answer a new unresolved purchase', async ({ page }, info) => {
  test.setTimeout(330_000);
  const mutations: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /confirm-cart|send-approved|send-autonomous|payments/.test(request.url())) mutations.push(request.url());
  });
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
