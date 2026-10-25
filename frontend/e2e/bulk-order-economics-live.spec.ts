import { expect, test, type Page } from '@playwright/test';
import {authenticateFixtureMerchant} from './helpers/fixtureMerchant';

test.beforeEach(async({context,baseURL})=>{
  await authenticateFixtureMerchant(context,baseURL!);
});

async function openBuyer(page: Page, label: string) {
  await page.addInitScript(value => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', value);
  }, `bulk-economics-${label}-${Date.now()}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
}

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
  const body = await response.text();
  if (!body.includes('data:')) return JSON.parse(body);
  for (const frame of body.replaceAll('\r\n', '\n').split('\n\n').reverse()) {
    if (!frame.includes('event: answer')) continue;
    const raw = frame.split('\n').filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trim()).join('\n');
    if (raw) return JSON.parse(raw);
  }
  throw new Error(`No completed answer frame returned: ${body.slice(0, 1200)}`);
}

test('bulk order within budget keeps one canonical role, amount and order result', async ({ page }) => {
  test.setTimeout(120_000);
  await openBuyer(page, 'fits');
  const answer = await send(page, 'I need 10 laptops with a total budget of AUD 30,000');

  expect(answer).toMatchObject({
    subject_role: 'PROCURE_SUBJECT',
    requested_quantity: 10,
    canonical_budget: { budget_max: 30_000 },
    bulk_budget: {
      quantity: 10,
      budget_scope: 'total',
      total_budget_cents: 3_000_000,
      budget_shortfall_cents: 0,
      verdict: 'fits',
    },
    action_executed: false,
  });
  expect(answer.products.length).toBeGreaterThan(0);
  await expect(page.getByText(/10 units.*fit.*30,000/i).last()).toBeVisible();
  await expect(page.getByTestId('turn-commercial-truth')).toContainText('PROCURE_SUBJECT');
  await expect(page.getByTestId('turn-commercial-truth')).toContainText('AUD 30,000');
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
});

test('underfunded bulk order reports exact shortfall with no false fitting shelf', async ({ page }) => {
  test.setTimeout(120_000);
  await openBuyer(page, 'shortfall');
  const answer = await send(page, 'I need 60 laptops with a total budget of AUD 30,000');

  expect(answer).toMatchObject({
    subject_role: 'PROCURE_SUBJECT',
    requested_quantity: 60,
    canonical_budget: { budget_max: 30_000 },
    bulk_budget: {
      quantity: 60,
      budget_scope: 'total',
      total_budget_cents: 3_000_000,
      required_total_cents: 3_774_000,
      budget_shortfall_cents: 774_000,
      max_affordable_quantity: 47,
      verdict: 'over_budget',
    },
    action_executed: false,
  });
  expect(answer.products).toHaveLength(0);
  await expect(page.getByText(/60 units.*37,740.*30,000/i).last()).toBeVisible();
  await expect(page.getByTestId('turn-commercial-truth')).toContainText('PROCURE_SUBJECT');
  await expect(page.getByTestId('turn-commercial-truth')).toContainText('AUD 30,000');
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
});
