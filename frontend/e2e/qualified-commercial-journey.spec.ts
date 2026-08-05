import { test, expect, Page } from '@playwright/test';

async function send(page: Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await input.press('Enter');
}

test('simulation-qualified evidence reaches explicit SKU, ATP, commitment and exact-shortfall RFQ', async ({ page }) => {
  test.setTimeout(240_000);
  let checkoutUpsellRequests = 0;
  let splitOfferRequests = 0;
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/recommend/checkout_upsell')) checkoutUpsellRequests += 1;
    if (request.url().includes('/api/v1/cart/split-offer')) splitOfferRequests += 1;
  });
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  const uid = `enterprise-e2e-qualified-${suffix}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await test.step('unqualified intent cannot reach inventory or a product slate', async () => {
    await send(page, 'Please recommend 80 laptops capable of simulating a digital twin for maintenance of mechanical machines.');
    await expect(page.getByTestId('stream-acknowledgement')).toBeVisible({ timeout: 1_500 });
    await expect(page.getByText(/Which exact software, standard, or workflow and version/i).last())
      .toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);
  });

  await test.step('explicit consent replays a versioned simulation contract and qualifies one SKU', async () => {
    await send(page, 'Search online for 80 laptops capable of digital twin simulation.');
    const consent = page.getByRole('button', { name: /Check approved sources/i });
    await expect(consent).toBeVisible();
    await consent.click();

    await expect(page.getByText(/HP OMEN MAX 16/i).first()).toBeVisible({ timeout: 60_000 });
    const add = page.getByRole('button', { name: 'Add', exact: true }).first();
    await expect(add).toBeVisible();

    await page.getByTitle('Decision Trace').click();
    const modal = page.getByTestId('decision-trace-modal');
    await modal.getByRole('button', { name: /^Reasoning/ }).click();
    const semantic = modal.getByTestId('semantic-resolution-trace');
    await expect(semantic).toContainText(/qualified catalog match/i);
    await expect(semantic).toContainText(/RGAM-0007/i);
    await expect(semantic).toContainText(/simulation contract only/i);
    await expect(semantic).toContainText(/not live vendor requirements or availability/i);
    await modal.getByTitle('Close').click();

    // The pre-selection trace may legitimately inspect the empty cart. Count
    // only requests for the selected 80-unit cart from this point onward.
    splitOfferRequests = 0;
    await add.click();
    await expect(page.locator('[data-testid^="qty-"]').first()).toHaveText('80');
  });

  await test.step('buyer commitment uses versioned ATP and drafts only the unresolved shortfall', async () => {
    const split = page.getByTestId('split-fulfillment-card');
    await expect(split).toBeVisible({ timeout: 30_000 });
    const rationale = await page.getByTestId('split-rationale').innerText();
    expect(rationale).toMatch(/supplier RFQ|follow/i);
    await page.getByTestId('split-confirm').click();
    await expect(page.getByTestId('cart-sourcing-note')).toContainText(/RFQ.*drafted/i, { timeout: 45_000 });

    await page.getByTitle('Decision Trace').click();
    const modal = page.getByTestId('decision-trace-modal');
    await modal.getByRole('button', { name: /^Commercial Journey/ }).click();
    await modal.getByRole('tab', { name: /Procurement/ }).click();
    const rfq = modal.getByTestId('proc-drafted-rfq');
    await expect(rfq).toBeVisible({ timeout: 45_000 });
    await expect(rfq).toContainText(/supplier-shortfall unit/i);
    await expect(rfq).toContainText(/human-gated.*not sent/i);
    await expect(modal.getByTestId('proc-rfq-body')).toContainText(/Quantity:/i);
  });

  expect(checkoutUpsellRequests).toBe(1);
  expect(splitOfferRequests).toBe(1);
});
