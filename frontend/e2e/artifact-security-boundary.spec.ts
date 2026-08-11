import { test, expect } from '@playwright/test';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import { readFileSync } from 'fs';
import { execFileSync } from 'child_process';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '../..');
const fixtureDir = resolve(repoRoot, 'frontend/test-results/generated-security-fixtures');
const mimeMismatch = resolve(fixtureDir, 'png_bytes_declared_as.pdf');
const hiddenInjection = resolve(fixtureDir, 'steg_prompt_injection.png');

test.beforeAll(() => {
  execFileSync('python', [
    resolve(repoRoot, 'scripts/gen_browser_security_fixtures.py'),
    '--out',
    fixtureDir,
  ], { cwd: repoRoot, stdio: 'pipe' });
});

test('rejected attachment remains visible and cannot become an attachment-free recommendation', async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto('/?e2e=artifact-security-boundary');
  const input = page.getByPlaceholder('Type your message...');
  if (!(await input.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /Ask Me/i }).click();
  }

  // Playwright intentionally bypasses the browser accept hint. The server must
  // identify the bytes and the UI must retain the failed attachment as a typed,
  // visible result rather than filter(Boolean) and continue attachment-free.
  await page.locator("input[type='file']").last().setInputFiles({
    name: 'png_bytes_declared_as.pdf',
    mimeType: 'image/png',
    buffer: readFileSync(mimeMismatch),
  });
  await expect(page.getByRole('img', { name: 'attached 1' })).toBeVisible();
  await input.fill('Recommend a product based on this attachment');
  await input.press('Enter');

  await expect(page.getByText(/attachment failed the upload safety gate/i)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/not used for recommendations, memory, or commercial actions/i).first()).toBeVisible();
  await expect(page.getByText(/closest in-catalog match for the uploaded image/i)).toHaveCount(0);
});

test('malicious or incompletely inspected image is blocked, traced, and records monitoring outcome', async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto('/?e2e=artifact-security-monitoring');
  const input = page.getByPlaceholder('Type your message...');
  if (!(await input.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /Ask Me/i }).click();
  }
  await page.locator("input[type='file']").last().setInputFiles(hiddenInjection);
  await expect(page.getByRole('img', { name: 'attached 1' })).toBeVisible();
  await input.fill('Use this image to recommend a laptop and prepare a bulk order');
  await input.press('Enter');

  // A confirmed finding is quarantined; a detector timeout is degraded. Both are blocked
  // terminal authority states and must still expose the same trace and monitoring proof.
  await expect(page.getByText(/^(Analysis pending|Under Review|Analysis degraded)$/))
    .toBeVisible({ timeout: 90_000 });
  const traceButton = page.getByTitle('Decision Trace').last();
  await expect(traceButton).toBeVisible({ timeout: 90_000 });
  await traceButton.click();
  await page.getByRole('button', { name: /Evidence & Risk/ }).click();
  const securityTab = page.getByTestId('trace-leaf-security');
  await expect(securityTab).toBeVisible({ timeout: 90_000 });
  await securityTab.click();
  const panel = page.getByRole('tabpanel', { name: /Security/i });
  await expect(page.getByTestId('trace-trust-strip').getByText(/Commercial actions blocked/i)).toBeVisible();
  await expect(panel.getByText(/commercial actions: blocked/i)).toBeVisible();
  await expect(panel.getByRole('heading', { name: 'Monitoring delivery' })).toBeVisible();
  await expect(panel.getByText(/no_receiver: skipped/i)).toBeVisible();
  await expect(panel.getByText(/Event schema: shopsquire.security.v1/i)).toBeVisible();
});
