import { expect, test } from '@playwright/test';

type ChatPayload = {
  query?: string;
  session_id?: string;
  uid?: string;
  memory_mode?: string;
};

const turns = [
  'I need 12 RGAM-0007 laptops for a design class.',
  'My total budget is 54000 AUD.',
  'Deliver them to Sydney.',
  'I need them by 18 September.',
  'What is the current status?',
  'Summarise the request.',
  'Keep the same laptop.',
  'Actually make that 14 units.',
  'Can you still source them?',
  'Use the same destination.',
  'Correction: deliver them to Parramatta.',
  'Does that change the ETA?',
  'Keep them under the same total budget.',
  'What part is confirmed?',
  'What part is still unknown?',
  'Do not substitute them.',
  'Keep the deadline.',
  'What would need human approval?',
  'Summarise without starting a new search.',
  'Confirm what you understood about those units.',
] as const;

test('20-turn corrections and pronouns retain one browser session and explicit product anchor', async ({ page }) => {
  const payloads: ChatPayload[] = [];

  await page.route('**/api/v1/chat/stream', (route) => route.abort());
  await page.route('**/api/v1/chat/query', async (route) => {
    payloads.push(route.request().postDataJSON() as ChatPayload);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        products: [],
        assistant_message: 'Request retained for RGAM-0007 in the current case.',
        requested_quantity: payloads.length >= 8 ? 14 : 12,
        next_questions: [],
        turn_intent: payloads.length === 1 ? 'SEARCH' : 'CASE_AMENDMENT',
        case_anchor: { case_id: 'case-browser-20', sku: 'RGAM-0007' },
        blocked: false,
      }),
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  const input = page.getByPlaceholder('Type your message...');

  for (const [index, query] of turns.entries()) {
    await input.fill(query);
    await input.press('Enter');
    await expect.poll(() => payloads.length, {
      message: `turn ${index + 1} should reach the governed chat boundary`,
    }).toBe(index + 1);
  }

  const sessions = new Set(payloads.map((payload) => payload.session_id || payload.uid));
  expect(sessions.size, 'all turns must remain in one browser-scoped conversation').toBe(1);
  expect([...sessions][0]).toBeTruthy();
  expect(payloads.every((payload) => payload.memory_mode === 'standard')).toBeTruthy();
  expect(payloads.map((payload) => payload.query)).toEqual([...turns]);
  expect(payloads[10].query).toContain('deliver them');
  expect(payloads[19].query).toContain('those units');
  await expect(page.getByText(/Request retained for RGAM-0007/).last()).toBeVisible();
});
