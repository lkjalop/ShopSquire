import { expect, test } from '@playwright/test';

test.skip(
  process.env.RUN_PORTFOLIO_SUPPLIER_CERTIFICATION !== '1',
  'Set RUN_PORTFOLIO_SUPPLIER_CERTIFICATION=1 against the portfolio-demo stack.',
);

test.beforeEach(async ({ request }) => {
  const requiredProfile = process.env.CERTIFICATION_RUNTIME_PROFILE;
  expect(
    requiredProfile,
    'configuration failure: set CERTIFICATION_RUNTIME_PROFILE for supplier certification',
  ).toBeTruthy();
  const response = await request.get('/health');
  expect(response.ok(), 'configuration failure: backend readiness endpoint unavailable').toBeTruthy();
  const readiness = await response.json();
  expect(readiness.runtime_modes?.profile).toBe(requiredProfile);
  expect(readiness.runtime_modes?.active?.supplier_transport).toBe('sandbox');
  expect(readiness.runtime_modes?.active?.supplier_autonomy).toBe('off');
});

test('high-value bulk request shows governed fulfilment choices and explicit exact confirmation', async ({ page }) => {
  test.setTimeout(150_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  const uid = `portfolio-supplier-${suffix}`;
  await page.addInitScript(
    (uid) => sessionStorage.setItem('uid', uid),
    uid,
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

  const selectionResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && /\/api\/v1\/shopping-cases\/[^/]+\/fulfillment-selections$/.test(response.url())
  ));
  await choices.getByRole('button', { name: /Ask suppliers for 27 compatible units/i }).click();
  const selectionResponse = await selectionResponsePromise;
  expect(selectionResponse.ok()).toBeTruthy();
  const selectionResult = await selectionResponse.json();
  const offers = continuation.getByTestId('supplier-offers');
  await expect(offers).toContainText(/27 × SCORP-126982 in 8 days/i);
  await expect(offers).toContainText(/SCORP-126982: unable to fulfil/i);
  await expect(offers).toContainText(/ACCEPTED.*covers the required exact-configuration quantity/i);
  await expect(offers).toContainText(/REJECTED.*no available quantity/i);
  await expect(offers).toContainText(/CONDITIONAL.*short by/i);
  await expect(offers).toContainText(/LATE.*after the requested deadline/i);
  await expect(offers).toContainText(/QUARANTINED.*identity or response integrity was not verified/i);
  const quarantined = offers.locator('label').filter({ hasText: /QUARANTINED/i });
  await expect(quarantined.getByRole('radio')).toBeDisabled();
  await expect(quarantined).toContainText(/unavailable for selection or cart confirmation/i);
  await expect(offers).toContainText(/Commercial status: QUALIFIED_LATE.*quantity late/i);
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
  const confirmationResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST' && /\/confirm-cart$/.test(response.url())
  ));
  await continuation.getByRole('button', { name: 'Confirm exact cart change' }).click();
  const confirmationResponse = await confirmationResponsePromise;
  expect(confirmationResponse.ok()).toBeTruthy();
  const confirmationResult = await confirmationResponse.json();
  await expect(continuation.getByRole('button', { name: 'Cart updated' })).toBeVisible({ timeout: 30_000 });
  const caseId = String(selectionResult.case_id);
  const now = new Date().toISOString();
  const inventoryObservationId = `browser-stock-correction-${suffix}`;
  const observation = await page.request.post(
    `/api/v1/shopping-cases/${caseId}/operational-observations`,
    {
      headers: { 'x-api-key': process.env.OWNER_API_KEY || 'local-owner-key' },
      data: {
        observation_id: inventoryObservationId,
        expected_revision: confirmationResult.revision,
        kind: 'inventory_quantity',
        subject_ref: `configuration:${confirmationResult.confirmed_sku}`,
        location_ref: 'warehouse:nearest-eligible',
        value: {
          quantity: 2,
          unit: 'unit',
          sku: confirmationResult.confirmed_sku,
          facility_kind: 'warehouse',
          destination_id: 'buyer-destination-token',
          destination_kind: 'region',
          deadline_days: 10,
          lead_time_days: 1,
          lane_capacity_units: 2,
        },
        source_type: 'inventory_system',
        evidence_ref: `browser-inventory-ledger:${suffix}`,
        known_at: now,
        effective_at: now,
      },
    },
  );
  expect(observation.ok(), await observation.text()).toBeTruthy();
  const observationResult = await observation.json();
  expect(observationResult.recomputed_stages).toEqual(['commercial', 'fulfilment', 'response']);
  expect(observationResult.operational_projection).toMatchObject({
    available_now: 2, requested_quantity: 30, remaining_quantity: 28,
    quantity_outcome: 'shortfall',
  });
  expect(observationResult.operational_projection.allocation).toMatchObject({
    status: 'complete', allocated_units: 30, shortfall_units: 0,
    authority: 'advisory_only', execution_allowed: false,
  });
  expect(observationResult.operational_projection.commercial_decision).toMatchObject({
    quantity_outcome: 'complete_by_deadline',
    cart_authority: 'none', supplier_send_authority: 'none',
  });
  expect(observationResult.tool_selection_receipt).toMatchObject({
    capability: 'inventory_availability', outcome: 'selected',
    commercial_authority_granted: false,
  });
  expect(observationResult.tool_selection_receipt.selected_deployment_ids).toEqual([
    'operator_intake:inventory_system',
  ]);
  expect(observationResult.ingestion_mode).toBe('operator_submitted_observation');
  expect(observationResult.evidence_watermark).toMatchObject({
    state: 'current', source_version: inventoryObservationId,
  });
  expect(observationResult.cart_mutations).toBe(0);

  const historyResponse = await page.request.get(
    `/api/v1/shopping-cases/${caseId}/decision-runs?uid=${encodeURIComponent(uid)}`,
  );
  expect(historyResponse.ok()).toBeTruthy();
  const history = await historyResponse.json();
  expect(history.latest.case_revision).toBe(observationResult.case_revision);
  expect(history.views.what_changed.from_revision).toBe(confirmationResult.revision);
  expect(history.views.what_changed.to_revision).toBe(observationResult.case_revision);
  expect(history.views.what_was_known_then.future_evidence_excluded).toBe(true);
  expect(history.views.who_can_fulfil_now.evidence_warning).toContain('not a live stock promise');
  expect(history.views.who_can_fulfil_now.available_now).toBe(2);
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

test('buyer can review wait and split paths then cancel without changing the cart', async ({ page }) => {
  test.setTimeout(150_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  await page.addInitScript(
    (uid) => sessionStorage.setItem('uid', uid),
    `portfolio-supplier-cancel-${suffix}`,
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
  await titan.getByRole('spinbutton').fill('30');
  await titan.getByRole('button', { name: /Review option|Propose cart change/i }).click();
  const continuation = page.getByTestId('supplier-continuation');
  await continuation.getByLabel('Needed within days').fill('10');
  await continuation.getByRole('button', { name: 'Assess fulfilment' }).click();

  const choices = continuation.getByTestId('fulfillment-choices');
  await choices.getByRole('button', { name: /Wait 8 days for the preferred fit/i }).click();
  await expect(continuation).toContainText(/Keep SCORP-126982 for all 30 units/i);
  await continuation.getByRole('button', { name: 'Change fulfilment choice' }).click();
  await continuation.getByTestId('fulfillment-choices')
    .getByRole('button', { name: /Take 3 now and source 27/i }).click();
  await expect(continuation).toContainText(/Keep SCORP-126982 for all 30 units/i);
  await expect(page.getByText(/Cart \(0\)/i).first()).toBeVisible();

  await continuation.getByRole('button', { name: 'Close review' }).click();
  await expect(continuation).toHaveCount(0);
  await expect(page.getByText(/Cart \(0\)/i).first()).toBeVisible();
  await expect(page.getByText(/Applied the explicitly confirmed fulfilment selection/i)).toHaveCount(0);
});
