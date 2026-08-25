import { expect, test, type Page, type Response } from '@playwright/test';

function responseEvents(response: Response): Promise<any[]> {
  return response.text().then((body) => {
    if ((response.headers()['content-type'] || '').includes('application/json')) {
      try { return [JSON.parse(body)]; } catch { return []; }
    }
    return body.split('\n')
      .filter((line) => line.startsWith('data: '))
      .map((line) => {
        try { return JSON.parse(line.slice(6)); } catch { return null; }
      })
      .filter(Boolean);
  });
}

async function latestAnswer(response: Response): Promise<any> {
  const events = await responseEvents(response);
  return [...events].reverse().find((event: any) => (
      event?.shopping_case_obligations || event?.ambiguity_exploration
  )) || {};
}

async function latestEventWith(response: Response, field: string): Promise<any> {
  const events = await responseEvents(response);
  return [...events].reverse().find((event: any) => (
    Object.prototype.hasOwnProperty.call(event, field)
  )) || {};
}

async function sendToChat(page: Page, query: string): Promise<Response> {
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && (
        /\/api\/v1\/chat\/(?:stream|query)(?:\?|$)/.test(response.url())
        || (
          /\/api\/v1\/shopping-cases\/interpretations(?:\?|$)/.test(response.url())
          && response.status() !== 204
        )
      )
  ), { timeout: 90_000 });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(query);
  await input.press('Enter');
  return responsePromise;
}

test('prospective arrival request reaches fulfilment instead of post-purchase refusal', async ({ page }) => {
  test.setTimeout(180_000);
  await page.addInitScript((uid) => sessionStorage.setItem('uid', uid), `arrival-${Date.now()}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });

  await sendToChat(page, 'I need gaming laptops for a studio.');
  await expect(page.getByTestId('ambiguity-exploration')).toBeVisible({ timeout: 60_000 });

  const response = await sendToChat(page, 'I need 15 of the top one. When can they all arrive?');
  expect(response.ok()).toBe(true);
  await expect(page.getByText(/I can't do that from chat yet/i)).toHaveCount(0);
  await expect(page.getByText(/human teammate can via the admin console/i)).toHaveCount(0);
});

test('ordinary gaming catalog exploration renders products without requiring research', async ({ page }) => {
  test.setTimeout(180_000);
  await page.addInitScript((uid) => sessionStorage.setItem('uid', uid), `ordinary-${Date.now()}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });

  const response = await sendToChat(page, 'help me with a gaming laptop? is 4000 ok?');
  expect(response.ok()).toBe(true);
  await expect(page.getByRole('button', { name: /^(Add|Add to Cart)$/i }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('ambiguity-exploration')).toHaveCount(0);
  await expect(page.getByText(/needs current external requirements before I can qualify products/i)).toHaveCount(0);
});

test('commercial turns remain bound to an ambiguous case and preserve its purpose', async ({ page }) => {
  test.setTimeout(240_000);
  await page.addInitScript((uid) => sessionStorage.setItem('uid', uid), `interrupt-${Date.now()}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  const initialResponse = await sendToChat(page, 'I need laptops for a factory rollout.');
  const initialAnswer = await latestAnswer(initialResponse);

  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible({ timeout: 60_000 });
  const caseId = initialAnswer.shopping_case_id || initialAnswer.ambiguity_exploration?.case_id;
  expect(caseId).toMatch(/^sc-/);

  const quantityResponse = await sendToChat(
    page,
    'I need 40 of the most expensive one within 3 days.',
  );
  const quantityAnswer = await latestAnswer(quantityResponse);
  expect(quantityResponse.ok()).toBe(true);
  expect(quantityResponse.request().postDataJSON()).toMatchObject({ shopping_case_id: caseId });
  expect(quantityAnswer.shopping_case_obligations).toEqual([
    'quantity', 'deadline', 'selected_product',
  ]);

  const supplierResponse = await sendToChat(
    page,
    'Yes, please raise a supplier enquiry for the shortfall.',
  );
  const supplierAnswer = await latestAnswer(supplierResponse);
  const purposeAnswer = await latestEventWith(
    supplierResponse,
    'shopping_case_retained_purpose',
  );
  expect(supplierAnswer.shopping_case_obligations).toEqual(['supplier_enquiry']);
  expect(purposeAnswer.shopping_case_retained_purpose).toBe(
    'I need laptops for a factory rollout.',
  );
  expect(purposeAnswer.shopping_case_retained_purpose).not.toMatch(/Buyer clarification to/i);
});

test('a product swap preserves the CAD purpose and quantity', async ({ page }) => {
  test.setTimeout(240_000);
  await page.addInitScript((uid) => sessionStorage.setItem('uid', uid), `swap-${Date.now()}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });

  const initialResponse = await sendToChat(page, 'I need 20 laptops for CAD work.');
  const initialAnswer = await latestAnswer(initialResponse);
  const caseId = initialAnswer.shopping_case_id || initialAnswer.ambiguity_exploration?.case_id;
  expect(caseId).toMatch(/^sc-/);

  const swapResponse = await sendToChat(
    page,
    'Actually swap that for the workstation one instead, same quantity.',
  );
  expect(swapResponse.ok()).toBe(true);
  expect(swapResponse.request().postDataJSON()).toMatchObject({
    shopping_case_id: caseId,
    confirmed_slots: { order_quantity: 20 },
  });
  const swapAnswer = await latestAnswer(swapResponse);
  const purposeAnswer = await latestEventWith(swapResponse, 'shopping_case_retained_purpose');
  expect(swapAnswer.shopping_case_obligations).toContain('selected_product');
  expect(swapAnswer.requested_quantity).toBe(20);
  expect(purposeAnswer.shopping_case_retained_purpose).toBe(
    'I need 20 laptops for CAD work.',
  );
  expect(purposeAnswer.shopping_case_retained_purpose).not.toMatch(/workstation one/i);
});
