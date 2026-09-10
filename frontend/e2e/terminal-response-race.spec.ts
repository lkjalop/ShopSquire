import { expect, test, type Route } from '@playwright/test';

// Transport fixtures deliberately control ordering. This is a browser UI gate,
// not a live-model or public-network research certificate.
test.describe.configure({ retries: 0 });
for (const lateFailure of [false, true]) {
  test(`new terminal survives late ${lateFailure ? 'failure' : 'success'}`, async ({ page }) => {
    const pending: Route[] = [];
    await page.route('**/api/v1/chat/stream', route => route.abort());
    await page.route('**/api/v1/chat/query', route => { pending.push(route); });
    await page.goto('/');
    await page.getByRole('button', { name: 'Ask Me!', exact: true }).click();
    const input = page.getByPlaceholder('Type your message...');
    await input.fill('I need a laptop');
    await input.press('Enter');
    await expect.poll(() => pending.length).toBe(1);
    await input.fill('Actually I need a computer chair');
    await input.press('Enter');
    await expect.poll(() => pending.length).toBe(2);
    const answer = (message: string, revision: number) => JSON.stringify({
      assistant_message: message, products: [], next_questions: [],
      terminal_outcome: {
        schema_version: 'turn-terminal-outcome-v1', operation_id: `operation-${revision}`,
        case_id: 'race-case', case_revision: revision, assistant_message: message,
        products: [], next_questions: [], catalog_authority: 'blocked', commerce_authority: 'none',
        ambiguity_exploration: null, product_shelves: null,
      },
    });
    await pending[1].fulfill({ status: 200, contentType: 'application/json', body: answer('CURRENT CHAIR OUTCOME', 2) });
    await expect(page.getByText('CURRENT CHAIR OUTCOME', { exact: true })).toBeVisible();
    const completed = page.waitForResponse(response => response.url().includes('/chat/query'));
    await pending[0].fulfill({ status: lateFailure ? 500 : 200, contentType: 'application/json',
      body: lateFailure ? JSON.stringify({ detail: 'STALE FAILURE' }) : answer('STALE LAPTOP OUTCOME', 9) });
    await completed;
    // Let the response's microtasks and React render settle before inspecting.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(page.getByText('CURRENT CHAIR OUTCOME', { exact: true })).toBeVisible();
    await expect(page.getByText('STALE LAPTOP OUTCOME', { exact: true })).toHaveCount(0);
    await expect(page.getByText('STALE FAILURE', { exact: false })).toHaveCount(0);
  });
}
