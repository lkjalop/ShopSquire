import { expect, test, type Page } from '@playwright/test';

async function send(page: Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(text);
  await input.press('Enter');
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 90_000 });
}

test('typed fit, quantity and deadline semantics produce governed alternatives', async ({ page }) => {
  test.setTimeout(300_000);
  const uid = `fit-deadline-${Date.now()}-${Math.random()}`;
  await page.addInitScript((value) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', value);
  }, uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await send(page, 'I need 30 laptops in 2 days to run Factory I/O for PLC simulation.');
  await expect(page.getByText(/external research not yet authorized/i)).toBeVisible();
  await expect(page.getByRole('region', { name: 'Provisional product shelves' })).toBeVisible();

  await page.getByRole('button', { name: 'Research approved sources' }).click();
  await expect(page.getByText(/compiled 3 scoped product claims/i).first())
    .toBeVisible({ timeout: 90_000 });
  const proof = page.getByTestId('buyer-research-proof');
  await proof.locator('summary').click();
  await expect(proof.getByTestId('ambiguity-accounting')).toContainText(/Paid calls: 0/i);

  const sharedShelf = page.getByRole('region', { name: 'Provisional product shelves' });
  const selectedCard = sharedShelf.locator('article').first();
  const selectedName = (await selectedCard.locator('strong').first().innerText()).trim();
  expect(selectedName.length).toBeGreaterThan(3);
  await expect(selectedCard).toContainText(/Conditional fit|Qualified fit/i);
  await selectedCard.getByRole('spinbutton').fill('30');
  await selectedCard.getByRole('button', { name: /Review option|Propose cart change/ }).click();

  const continuation = page.getByTestId('supplier-continuation');
  await expect(continuation).toContainText(selectedName);
  await continuation.getByLabel('Needed within days').fill('2');
  await continuation.getByRole('button', { name: 'Assess fulfilment' }).click();
  await expect(page.getByTestId('fulfillment-choices')).toContainText(/supplier|next-best|split|wait/i);

  await page.getByRole('button', { name: /Ask suppliers for/i }).click();
  const offers = page.getByTestId('supplier-offers');
  await expect(offers).toContainText(/8 days.*LATE|LATE.*8 days/is);
  await expect(offers).toContainText(/REJECTED/i);

  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal).toBeVisible();
  await modal.getByRole('button', { name: /^Commercial Journey/ }).click();
  await modal.getByRole('tab', { name: /Procurement/ }).click();
  await expect(modal).toContainText(/supplier|fulfilment|2 day/i);
});
