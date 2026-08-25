import { expect, test } from '@playwright/test';

test('shopping-case fast lane returns provisional shelves before external research', async ({ page }) => {
  test.setTimeout(90_000);
  const uid = `fast-lane-${Date.now()}-${Math.random()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });

  const input = page.getByPlaceholder('Type your message...');
  const purpose = 'I need a laptop to simulate a PLC-controlled factory using Factory I/O.';
  await input.fill(purpose);
  await input.press('Enter');

  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId('buyer-research-status')).toContainText(/external research is off/i);
  await expect(panel).toContainText(/external calls: 0/i);
  await expect(page.getByTestId('product-shelves')).toBeVisible();

  // Use Playwright's API context for the typed timing receipt. Chromium may
  // release a fetch response body after the React consumer has read it, while
  // this request still traverses the same deployed HTTP boundary.
  const response = await page.request.post('/api/v1/shopping-cases/interpretations', {
    data: {
      uid: `${uid}-receipt`,
      retained_purpose: purpose,
      storefront_taxonomy_handle: 'el-6-6',
    },
  });
  expect(response.ok()).toBe(true);
  const payload = await response.json();
  const timing = payload.ambiguity_exploration?.timing_envelope;
  expect(timing?.schema_version).toBe('shopping-case-fast-lane-timing-v1');
  expect(timing?.deadline_status).toBe('within_deadline');
  expect(timing?.external_calls).toBe(0);
  expect(timing?.total_ms).toBeLessThanOrEqual(timing?.deadline_ms);

});
