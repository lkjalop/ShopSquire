import { test, expect, Page } from '@playwright/test';

const UID = `e2e-procurement-${Date.now()}`;

async function send(page: Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  if (!(await input.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /Ask Me/i }).click();
  }
  await input.fill(text);
  await input.press('Enter');
}

async function openProcurementTrace(page: Page) {
  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal).toBeVisible();
  await modal.getByRole('button', { name: /Procurement/ }).click();
  await expect(modal.getByTestId('proc-drafted-rfq')).toBeVisible({ timeout: 45_000 });
  return modal;
}

test('demo procurement journey: clear, bulk split, RFQ evidence, amendment and redraft', async ({ page }) => {
  test.setTimeout(240_000);
  await page.addInitScript((uid) => sessionStorage.setItem('uid', uid), UID);
  await page.goto('/');

  await test.step('clear the cart through NLP', async () => {
    await send(page, 'clear my cart');
    await expect(page.getByText(/cart is (?:already )?empty|cleared your cart|cart has been cleared/i).last())
      .toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Cart is empty/i)).toBeVisible();
  });

  await test.step('request and add 25 work laptops', async () => {
    await send(page, 'what laptops for work? budget 1500 to 1900, I need about 25');
    const add = page.getByRole('button', { name: 'Add', exact: true }).first();
    const perItem = page.getByRole('button', { name: 'Per item', exact: true });
    await expect(add.or(perItem)).toBeVisible({ timeout: 75_000 });
    if (await perItem.isVisible().catch(() => false)) {
      await perItem.click();
    }
    await expect(add).toBeVisible({ timeout: 75_000 });
    await add.click();
    await expect(page.locator('[data-testid^="qty-"]').first()).toHaveText('25');
  });

  let originalDraft = '';
  await test.step('confirm the split and inspect the drafted supplier RFQ', async () => {
    await expect(page.getByTestId('split-fulfillment-card')).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('split-confirm').click();
    await expect(page.getByTestId('cart-sourcing-note')).toContainText(/RFQ.*drafted/i, { timeout: 45_000 });

    const modal = await openProcurementTrace(page);
    await expect(modal.getByTestId('proc-supplier-channel')).toContainText(/email|phone|portal|EDI|API|cXML/i);
    await expect(modal.getByTestId('proc-supplier-terms')).not.toContainText(/^\s*—\s*$/);
    originalDraft = await modal.getByTestId('proc-rfq-body').innerText();
    expect(originalDraft.trim().length).toBeGreaterThan(40);
    await modal.getByTitle('Close').click();
  });

  await test.step('amend the selected laptop to 15 and redraft', async () => {
    await send(page, 'actually make the laptop 15 instead');
    const card = page.getByTestId('multi-intent-card');
    const quantity = page.locator('[data-testid^="qty-"]').first();
    await quantity.scrollIntoViewIfNeeded();
    const inlineConfirm = page.getByRole('button', { name: /Confirm.*apply to cart/i });
    await expect(card.or(inlineConfirm)).toBeVisible({ timeout: 75_000 });
    await expect(quantity).toHaveText('25');
    if (await card.isVisible().catch(() => false)) {
      const amendment = card.locator('[data-testid^="multi-intent-amend-"]').first();
      await expect(amendment).toContainText('15');
      await card.getByRole('button', { name: /Confirm qty|Apply all/i }).click();
    } else {
      await inlineConfirm.click();
    }

    await expect(quantity).toHaveText('15');
    const reconfirm = page.getByTestId('split-confirm');
    await expect(reconfirm).toBeVisible({ timeout: 30_000 });
    await reconfirm.scrollIntoViewIfNeeded();
    await reconfirm.click();
    await expect(page.getByTestId('cart-sourcing-note')).toContainText(/RFQ.*drafted/i, { timeout: 45_000 });

    const modal = await openProcurementTrace(page);
    const amendedDraft = await modal.getByTestId('proc-rfq-body').innerText();
    expect(amendedDraft.trim().length).toBeGreaterThan(40);
    expect(amendedDraft).not.toEqual(originalDraft);
  });
});
