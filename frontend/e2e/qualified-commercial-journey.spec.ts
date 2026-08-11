import { expect, test, type Page } from '@playwright/test';

async function send(page: Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await input.press('Enter');
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 90_000 });
}

test('ambiguous research continues into an explicit synthetic supplier decision', async ({ page }) => {
  test.setTimeout(300_000);
  const uid = `enterprise-e2e-${Date.now()}-${Math.random()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await send(
    page,
    'I need 30 laptops within 10 days to run Factory I/O for a PLC-controlled factory simulation.',
  );

  await expect(page.getByText(/Which named software and version/i)).toBeVisible();
  await expect(page.getByRole('region', { name: 'Provisional product shelves' })).toBeVisible();
  await expect(page.getByText(/external research not yet authorized/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Review option' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Research approved sources' }).click();
  await expect(page.getByText(/Approved-source research completed in the same shopping case/i))
    .toBeVisible({ timeout: 90_000 });
  const researchProof = page.locator('details').filter({ hasText: 'Research proof' }).last();
  await researchProof.locator('summary').click();
  await expect(researchProof.getByTestId('ambiguity-accounting')).toContainText(/Paid calls: 0/i);

  const firstShelf = page.getByRole('region', { name: 'Provisional product shelves' })
    .locator('article').first();
  await expect(firstShelf).toBeVisible();
  await firstShelf.getByRole('spinbutton').fill('30');
  await firstShelf.getByRole('button', { name: /Review option|Propose cart change/ }).click();

  const continuation = page.getByTestId('supplier-continuation');
  await expect(continuation).toContainText(/nothing has changed yet/i);
  await expect(continuation).toContainText(/30/);
  await continuation.getByLabel('Needed within days').fill('10');
  await continuation.getByRole('button', { name: 'Assess fulfilment' }).click();
  await expect(page.getByTestId('fulfillment-choices')).toBeVisible();

  await page.getByRole('button', { name: /Ask suppliers for/i }).click();
  const offers = page.getByTestId('supplier-offers');
  await expect(offers).toContainText(/Synthetic certification responses/i);
  await expect(offers).toContainText(/ACCEPTED/i);
  await expect(offers).toContainText(/REJECTED/i);
  await expect(page.getByTestId('real-supplier-locked')).toContainText(/human RFQ preview/i);

  const accepted = offers.locator('label').filter({ hasText: /ACCEPTED/i }).first();
  await accepted.getByRole('radio').check();
  await expect(continuation.getByText('Final confirmation')).toBeVisible();
  await expect(continuation).toContainText(/not a purchase commitment/i);
  await continuation.getByRole('button', { name: 'Confirm exact cart change' }).click();
  await expect(continuation.getByRole('button', { name: 'Cart updated' })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Applied the explicitly confirmed fulfilment selection: 30 ×/i))
    .toBeVisible();
});
