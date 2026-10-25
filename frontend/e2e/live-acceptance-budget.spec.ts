import { expect, test } from '@playwright/test';
import { registerBuyer } from './helpers/registeredBuyer';

test.describe.configure({ retries: 0 });
for (const stretch of [false, true]) test(`live manual acceptance preserves case budget and cannot verify partial evidence (stretch=${stretch})`, async ({ page }, info) => {
  test.setTimeout(240_000);
  const mutations: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /confirm-cart|send-approved|send-autonomous|payments/.test(request.url())) mutations.push(request.url());
  });
  await registerBuyer(page.context());
  await page.goto('/');
  await page.getByRole('button', { name: 'Ask Me!', exact: true }).click();
  await page.getByPlaceholder('Type your message...').fill('I need a laptop under AUD 3000 for Rockwell Emulate3D locally');
  await page.getByPlaceholder('Type your message...').press('Enter');
  const manual = page.getByRole('button', { name: 'Enter specifications', exact: true });
  await expect(manual).toBeVisible({ timeout: 150_000 });
  await manual.click();
  await page.getByRole('textbox', { name: 'Manual specifications' }).fill('RAM 32GB minimum');
  await page.getByRole('button', { name: 'Review extracted requirements', exact: true }).click();
  const accept = page.getByRole('button', { name: 'Use selected provisionally', exact: true }).last();
  await expect(accept).toBeVisible({ timeout: 30_000 });
  if (stretch) {
    await page.getByRole('checkbox', { name: 'Allow bounded stretch for this review only' }).last().check();
    await page.getByRole('spinbutton', { name: 'Stretch maximum AUD per item' }).last().fill('3300');
  }
  const responsePromise = page.waitForResponse(response => /requirement-proposals\/.*\/accept/.test(response.url()), { timeout: 30_000 });
  await accept.click();
  const response = await responsePromise;
  const body = await response.json();
  await info.attach('acceptance-summary', { body: JSON.stringify({ status: response.status(), budget: body.budget_context, detail: body.detail }), contentType: 'application/json' });
  expect(response.status()).toBe(200);
  expect(body.budget_context).toMatchObject({ unit_budget_cents: 300000, quantity: 1 });
  if (stretch) expect(body.stretch_consent).toMatchObject({ original_unit_budget_cents: 300000, unit_cap_cents: 330000, scope: 'this_acceptance_only', commerce_authority: 'none' });
  else expect(body.stretch_consent).toBeNull();
  for (const shelf of body.product_shelves?.shelves || []) {
    if (!stretch) expect(shelf.budget_band).not.toBe('stretch');
    for (const item of [...shelf.initial, ...shelf.remaining]) {
      expect(item.price_cents).toBeLessThanOrEqual(stretch ? 330000 : 300000);
      expect(item.fit_status).not.toBe('qualified');
    }
  }
  await expect(page.getByText('Reviewed for provisional browsing.', { exact: true })).toBeVisible();
  expect(mutations).toEqual([]);
});
