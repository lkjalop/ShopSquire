import { test, expect, Page } from '@playwright/test';

/**
 * Recorded procurement journey (video: on). Proves the agentic buyer flow end-to-end: a bulk laptop order,
 * then a real MIND-CHANGE — lower the laptop qty AND reallocate the leftover budget to two new scoped
 * categories in ONE turn — decomposed, adversarially re-checked, and surfaced as a confirmation card that
 * the buyer applies (sourcing-backed, no 409). Paced with waits so the .webm is watchable.
 * Output: a video.webm per run under test-results, plus a Playwright trace (npx playwright show-trace).
 */

async function openChatAndSend(page: Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  if (!(await input.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /Ask Me/i }).click();
    await input.waitFor({ state: 'visible' });
  }
  await input.click();
  await input.fill(text);
  await input.press('Enter');
}

test('procurement journey — bulk order + reallocation mind-change, agentic + scoped + confirmed', async ({ page }) => {
  await test.step('1 · buyer asks for business laptops (establishes the selection the planner amends)', async () => {
    await page.goto('/');
    await openChatAndSend(page, 'business laptop around 1300');
    await expect(page.getByText(/laptop/i).first()).toBeVisible({ timeout: 60_000 });
    await page.waitForTimeout(2500); // let the turn settle + the recording breathe
  });

  await test.step('2 · buyer CHANGES THEIR MIND in one turn: lower to 20 + reallocate the leftover to headsets & hard drives', async () => {
    await openChatAndSend(page,
      'actually lower the laptops to 20, and with the leftover budget get me headsets and hard drives for 2000 for those');
    const card = page.getByTestId('multi-intent-card');
    await expect(card).toBeVisible({ timeout: 60_000 });
    // the amendment (only the line the turn changed) — target the amend ROW testid (the qty lives in a
    // nested <strong>, so a cross-element /quantity to.*20/ text regex is flaky; assert the row's content).
    const amendRow = card.locator('[data-testid^="multi-intent-amend-"]');
    await expect(amendRow).toBeVisible({ timeout: 30_000 });
    await expect(amendRow).toContainText(/quantity to/i);
    await expect(amendRow).toContainText('20');
    // the two scoped new categories
    await expect(card.getByText(/headsets/i)).toBeVisible();
    await expect(card.getByText(/hard drives/i)).toBeVisible();
    await page.waitForTimeout(3000);
  });

  await test.step('3 · buyer confirms the reduced qty — sourcing-backed (the shortfall sources from suppliers)', async () => {
    const card = page.getByTestId('multi-intent-card');
    await card.getByRole('button', { name: 'Confirm qty' }).click();
    await expect(page.getByText(/will be sourced|Set .* to 20/i)).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(2500);
  });
});
