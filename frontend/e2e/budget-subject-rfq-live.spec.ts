import { expect, test, type Page } from '@playwright/test';


async function send(page: Page, query: string) {
  const responsePromise = page.waitForResponse(
    response => response.request().method() === 'POST'
      && /\/api\/v1\/chat\/(?:stream|query)$/.test(response.url()),
    { timeout: 90_000 },
  );
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(query);
  await input.press('Enter');
  const response = await responsePromise;
  const raw = await response.text();
  if (!raw.includes('data:')) return JSON.parse(raw);
  const frames = raw.replaceAll('\r\n', '\n').split('\n\n').reverse();
  for (const frame of frames) {
    if (!frame.includes('event: answer')) continue;
    const data = frame.split('\n').filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trim()).join('\n');
    if (data) return JSON.parse(data);
  }
  throw new Error(`No completed answer frame returned: HTTP ${response.status()} ${raw.slice(0, 1200)}`);
}


test('software budget truth is consistent and off-catalog sourcing is explicit and draft-only', async ({ page }) => {
  test.setTimeout(180_000);
  const uid = `budget-role-rfq-${Date.now()}`;
  await page.addInitScript(value => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', value);
  }, uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const answer = await send(page, 'Buy 200 CRM seats under AUD 120k annually');
  expect(answer.subject_role).toBe('PROCURE_SUBJECT');
  expect(answer.canonical_budget).toMatchObject({ budget_max: 120_000, mode: 'ceiling' });
  expect(answer.commercial_terms).toMatchObject({
    currency: 'AUD', quantity: 200, quantity_unit: 'seat', billing_cadence: 'annual',
  });
  expect(answer.products || []).toHaveLength(0);
  expect(answer.off_catalog).toMatchObject({
    supplier_rfq_offer: true,
    shopping_case_id: answer.shopping_case_id,
    case_revision: answer.case_revision,
    trace_id: answer.trace_id,
  });
  expect(answer.turn_read_model).toMatchObject({
    case_revision: answer.case_revision,
    subject_role: 'PROCURE_SUBJECT',
    canonical_budget: { budget_max: 120_000 },
    commercial_terms: { quantity: 200, quantity_unit: 'seat' },
  });

  const panelTruth = page.getByTestId('turn-commercial-truth');
  await expect(panelTruth).toContainText('PROCURE_SUBJECT');
  await expect(panelTruth).toContainText('AUD 120,000');
  const sourcing = page.getByTestId('off-catalog-sourcing');
  await expect(sourcing).toContainText(/will not contact a supplier/i);

  await page.getByTitle('Decision Trace').click();
  await expect(page.getByTestId('trace-subject-role')).toHaveText('PROCURE_SUBJECT');
  await expect(page.getByTestId('trace-budget')).toHaveText('AUD 120,000');
  await page.getByTestId('decision-trace-modal').getByTitle('Close').click();

  const sourcingResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/fulfillment/cases/from-off-catalog'),
  );
  await sourcing.getByTestId('create-sourcing-request').click();
  const sourcingPayload = await (await sourcingResponse).json();
  expect(sourcingPayload).toMatchObject({
    shopping_case_id: answer.shopping_case_id,
    case_revision: answer.case_revision,
    supplier_contacted: false,
    draft: {
      status: 'internal_sourcing_brief',
      requires_operator_supplier_resolution: true,
    },
  });
  await expect(sourcing.getByTestId('off-catalog-sourcing-created'))
    .toContainText(/No supplier has been contacted/i);
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
});
