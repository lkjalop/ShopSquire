import { expect, test, type Page } from '@playwright/test';

test.skip(
  process.env.MODEL_CERTIFICATION_FAULT_PROFILE !== 'ollama_offline',
  'Requires the production-shaped closed-port Ollama profile.',
);

async function send(page: Page, query: string) {
  const responsePromise = page.waitForResponse(
    response => response.request().method() === 'POST'
      && /\/api\/v1\/chat\/(?:stream|query)$/.test(response.url()),
    { timeout: 45_000 },
  );
  await page.getByPlaceholder('Type your message...').fill(query);
  await page.getByPlaceholder('Type your message...').press('Enter');
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  const body = await response.text();
  if (!body.includes('data:')) return JSON.parse(body);
  for (const frame of body.replaceAll('\r\n', '\n').split('\n\n').reverse()) {
    if (!frame.includes('event: answer')) continue;
    const raw = frame.split('\n').filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trim()).join('\n');
    if (raw) return JSON.parse(raw);
  }
  throw new Error('completed answer frame missing');
}

test('Ollama offline preserves canonical order truth and fails closed', async ({ page }) => {
  test.setTimeout(90_000);
  const uid = `model-offline-${Date.now()}`;
  await page.addInitScript(value => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const answer = await send(
    page,
    'I need 60 laptops with a total budget of AUD 30,000',
  );

  expect(answer).toMatchObject({
    subject_role: 'PROCURE_SUBJECT',
    requested_quantity: 60,
    canonical_budget: { budget_max: 30_000 },
    bulk_budget: {
      quantity: 60,
      total_budget_cents: 3_000_000,
      verdict: 'over_budget',
    },
    action_executed: false,
  });
  expect(answer.products).toHaveLength(0);
  expect(answer.router_outcome).toMatchObject({
    status: 'source_unavailable',
    source: 'fallback:model_unavailable',
    late_results_accepted: false,
  });
  expect(answer.model_invocation?.outcome).not.toBe('ok');
  await expect(page.getByTestId('turn-commercial-truth')).toContainText('PROCURE_SUBJECT');
  await expect(page.getByTestId('turn-commercial-truth')).toContainText('AUD 30,000');
  await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
});
