import { expect, test } from '@playwright/test';

test.skip(
  process.env.RUN_LIVE_BUYER_SOURCE_CERTIFICATION !== '1',
  'Set RUN_LIVE_BUYER_SOURCE_CERTIFICATION=1 against the governed local stack.',
);

test('buyer checks an official URL locally then explicitly authorizes canonical research', async ({ page }) => {
  test.setTimeout(120_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  await page.addInitScript(
    (uid) => sessionStorage.setItem('uid', uid),
    `buyer-source-live-${suffix}`,
  );
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need to simulate a PLC-controlled factory and cyberattacks against the OT network.');
  await input.press('Enter');

  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible({ timeout: 45_000 });
  await panel.getByRole('button', { name: 'Use official link or vendor' }).click();
  await panel.getByLabel('Official requirements URL or named vendor').fill(
    'https://docs.factoryio.com/manual/system-requirements/',
  );
  await panel.getByRole('button', { name: 'Check source' }).click();
  await expect(panel.getByRole('status')).toContainText(/resolved.*reviewed source matched/i);
  await expect(panel.getByTestId('ambiguity-accounting')).toContainText(/External calls: 0/i);

  await panel.getByRole('button', { name: 'Research matched canonical source' }).click();
  await expect(page.getByText(/fetched the reviewed canonical publisher page/i)).toBeVisible({ timeout: 60_000 });
  await expect(panel).toContainText(/Status: Researched|Status: Context researched|Status: Research completed/i);
  await expect(page.getByText(/no cart or supplier action was authorized/i)).toBeVisible();
});
