import { expect, test } from '@playwright/test';

test.skip(
  process.env.RUN_PORTFOLIO_SUPPLIER_CERTIFICATION !== '1',
  'Set RUN_PORTFOLIO_SUPPLIER_CERTIFICATION=1 against the portfolio-demo stack.',
);

test('high-value bulk request shows governed fulfilment choices and explicit exact confirmation', async ({ page }) => {
  test.setTimeout(150_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  await page.addInitScript(
    (uid) => sessionStorage.setItem('uid', uid),
    `portfolio-supplier-${suffix}`,
  );
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need to simulate a PLC-controlled factory and cyberattacks against the OT network.');
  await input.press('Enter');

  const interpretation = page.getByTestId('ambiguity-exploration');
  await expect(interpretation).toBeVisible({ timeout: 45_000 });
  await interpretation.getByRole('button', { name: 'Use official link or vendor' }).click();
  await interpretation.getByLabel('Official requirements URL or named vendor').fill(
    'https://docs.factoryio.com/manual/system-requirements/',
  );
  await interpretation.getByRole('button', { name: 'Check source' }).click();
  await interpretation.getByRole('button', { name: 'Research matched canonical source' }).click();
  await expect(page.getByText(/fetched the reviewed canonical publisher page/i)).toBeVisible({ timeout: 60_000 });

  const titan = page.getByTestId('product-shelves').locator('article')
    .filter({ hasText: 'MSI Titan 18 HX A2WJ RTX 5090 Laptop' }).first();
  await expect(titan).toBeVisible();
  await titan.getByRole('spinbutton').fill('30');
  await titan.getByRole('button', { name: /Review option|Propose cart change/i }).click();

  const continuation = page.getByTestId('supplier-continuation');
  await expect(continuation).toBeVisible();
  await expect(continuation).toContainText(/3 verified now · 27 require another fulfilment path/i);
  await continuation.getByLabel('Needed within days').fill('10');
  await continuation.getByRole('button', { name: 'Assess fulfilment' }).click();
  const choices = continuation.getByTestId('fulfillment-choices');
  await expect(choices).toContainText(/Take 3 now and source 27/i);
  await expect(choices).toContainText(/Wait 8 days for the preferred fit/i);
  await expect(choices).not.toContainText(/Wait 8 days.*misses requested deadline/i);
  await expect(choices).toContainText(/Ask suppliers for 27 compatible units/i);

  await choices.getByRole('button', { name: /Ask suppliers for 27 compatible units/i }).click();
  const offers = continuation.getByTestId('supplier-offers');
  await expect(offers).toContainText(/27 × SCORP-126982 in 8 days/i);
  await expect(offers).toContainText(/SCORP-126982: unable to fulfil/i);
  await expect(offers).toContainText(/ACCEPTED.*covers the required exact-configuration quantity/i);
  await expect(offers).toContainText(/REJECTED.*no available quantity/i);
  await expect(offers).toContainText(/CONDITIONAL.*short by/i);
  await expect(offers).toContainText(/LATE.*21 days misses the 10-day window/i);
  await expect(offers).not.toContainText(/proposed substitute/i);
  await offers.getByLabel(/27 × SCORP-126982.*exact configuration/i).check();
  const commercialReview = continuation.getByTestId('high-value-order-warning');
  await expect(commercialReview).toContainText(/total value is at least AUD 30,000/i);
  await expect(commercialReview).toContainText(/quantity is over 10 and unit price is at least AUD 4,000/i);
  await expect(commercialReview).toContainText(/portfolio enforcement: advisory only/i);
  await expect(commercialReview).toContainText(/purchase authority: unchanged/i);
  await expect(continuation.getByTestId('real-supplier-locked')).toContainText(/explicit send authorization/i);
  if (process.env.PORTFOLIO_SUPPLIER_SCREENSHOT_PATH) {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.screenshot({ path: process.env.PORTFOLIO_SUPPLIER_SCREENSHOT_PATH });
  }
  await continuation.getByRole('button', { name: 'Confirm exact cart change' }).click();
  await expect(continuation.getByRole('button', { name: 'Cart updated' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Applied the explicitly confirmed fulfilment selection: 30 ×/i)).toBeVisible();
});

test('unavailable flagship offers a proportionate conditional substitute without silent cart change', async ({ page }) => {
  test.setTimeout(150_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  await page.addInitScript(
    (uid) => sessionStorage.setItem('uid', uid),
    `portfolio-substitute-${suffix}`,
  );
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need to simulate a PLC-controlled factory and cyberattacks against the OT network.');
  await input.press('Enter');

  const interpretation = page.getByTestId('ambiguity-exploration');
  await expect(interpretation).toBeVisible({ timeout: 45_000 });
  await interpretation.getByRole('button', { name: 'Use official link or vendor' }).click();
  await interpretation.getByLabel('Official requirements URL or named vendor').fill(
    'https://docs.factoryio.com/manual/system-requirements/',
  );
  await interpretation.getByRole('button', { name: 'Check source' }).click();
  await interpretation.getByRole('button', { name: 'Research matched canonical source' }).click();
  await expect(page.getByText(/fetched the reviewed canonical publisher page/i)).toBeVisible({ timeout: 60_000 });

  const flagship = page.getByTestId('product-shelves').locator('article')
    .filter({ hasText: 'ASUS ROG Zephyrus Duo GX651 RTX 5090 Laptop' }).first();
  await flagship.getByRole('spinbutton').fill('30');
  await flagship.getByRole('button', { name: /Review option|Propose cart change/i }).click();

  const continuation = page.getByTestId('supplier-continuation');
  await expect(continuation).toContainText(/0 verified now · 30 require another fulfilment path/i);
  const proportionate = continuation.getByTestId('proportionate-alternatives');
  await expect(proportionate).toContainText(/MSI Titan 18 HX A2WJ RTX 5090 Laptop/i);
  await expect(proportionate).toContainText(/31% lower/i);
  await continuation.getByRole('button', { name: 'Assess fulfilment' }).click();
  const choices = continuation.getByTestId('fulfillment-choices');
  await choices.getByRole('button', { name: /next-best verified option now/i }).click();

  const offers = continuation.getByTestId('supplier-offers');
  const substitute = offers.getByLabel(/30 × SCORP-126982.*proposed substitute/i);
  await expect(substitute).toBeVisible();
  await expect(offers).toContainText(/CONDITIONAL.*substitute.*buyer acceptance/i);
  await expect(page.getByText(/Cart \(0\)/i).first()).toBeVisible();
  await substitute.check();
  await continuation.getByRole('button', { name: 'Confirm exact cart change' }).click();
  await expect(continuation.getByRole('button', { name: 'Cart updated' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Applied the explicitly confirmed fulfilment selection: 30 ×/i)).toBeVisible();
});
