import { expect, test } from '@playwright/test';


test('temporary chat rotates the browser epoch and marks requests no-memory', async ({ page }) => {
  const payloads: any[] = [];
  await page.route('**/api/v1/chat/stream', (route) => route.abort());
  await page.route('**/api/v1/chat/query', async (route) => {
    payloads.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        products: [],
        assistant_message: 'Bounded response.',
        next_questions: [],
        turn_intent: 'POLICY_QUESTION',
        blocked: false,
      }),
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('first bounded question');
  await input.press('Enter');
  await expect.poll(() => payloads.length).toBe(1);

  await page.getByTestId('temporary-chat-toggle').click();
  await expect(page.getByTestId('temporary-chat-toggle')).toHaveAttribute('aria-pressed', 'true');
  await input.fill('temporary bounded question');
  await input.press('Enter');
  await expect.poll(() => payloads.length).toBe(2);

  expect(payloads[0].memory_mode).toBe('standard');
  expect(payloads[1].memory_mode).toBe('temporary');
  expect(payloads[0].session_id).toBeTruthy();
  expect(payloads[1].session_id).toBeTruthy();
  expect(payloads[1].session_id).not.toBe(payloads[0].session_id);
});
