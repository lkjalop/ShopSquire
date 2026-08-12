import { expect, test } from '@playwright/test';


test('buyer disconnect during live discovery does not strand backend responsiveness', async ({ page, request }) => {
  test.setTimeout(150_000);
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', `disconnect-${Date.now()}`);
  });
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(
    'Is this laptop suitable for an unfamiliar scientific solver whose official publisher requirements must be checked?',
  );
  await input.press('Enter');
  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible({ timeout: 65_000 });
  const research = panel.getByRole('button', {
    name: /Discover official sources|Research approved sources/i,
  });
  const dispatched = page.waitForRequest(
    req => req.method() === 'POST' && /\/shopping-cases\/[^/]+\/research$/.test(req.url()),
    { timeout: 30_000 },
  );
  await research.click({ noWaitAfter: true });
  await dispatched;
  await page.close();

  const started = Date.now();
  const health = await request.get('http://127.0.0.1:8080/healthz', { timeout: 15_000 });
  expect(health.ok()).toBe(true);
  expect(Date.now() - started).toBeLessThan(15_000);
});
