import { expect, test } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';


test('two-turn procurement decision lab renders and seals the canonical certificate', async ({ page }, testInfo) => {
  test.setTimeout(150_000);
  await page.goto('/?surface=procurement-certification');
  const showcase = page.getByTestId('procurement-certification-showcase');
  await expect(showcase).toBeVisible({ timeout: 60_000 });
  await expect(showcase).toContainText('Sydney');
  await expect(showcase).toContainText('45 units');
  await expect(showcase).toContainText('Perth');
  await expect(showcase).toContainText('15 units');
  await expect(showcase).toContainText('Workload locationsExcluded');
  await expect(showcase).toContainText('Before consent0 calls');
  await expect(showcase).toContainText('No RFQ was sent and no stock was reserved');
  await expect(showcase).toContainText('Authority NONE');

  const api = await page.request.post(
    '/api/v1/certification/procurement/conversational-spatiotemporal/evaluate',
    {
      headers: { 'x-api-key': process.env.MERCHANT_API_KEY || 'local-merchant-key' },
      data: {},
    },
  );
  expect(api.ok(), await api.text()).toBeTruthy();
  const domainCertificate = await api.json();
  expect(domainCertificate.passed).toBe(true);
  expect(Object.values(domainCertificate.invariants).every(Boolean)).toBe(true);
  const browserCertificate: any = {
    schema_version: 'conversational-spatiotemporal-browser-certificate-v1',
    observed_at: new Date().toISOString(),
    execution: 'live_playwright_browser',
    fixture: true,
    live_network_certified: false,
    domain_artifact_sha256: domainCertificate.artifact_sha256,
    case_revision: domainCertificate.amended_state.revision,
    destinations: domainCertificate.amended_state.destinations,
    canonical_truth: domainCertificate.canonical_truth,
    invariants: domainCertificate.invariants,
  };
  browserCertificate.browser_artifact_sha256 = createHash('sha256')
    .update(JSON.stringify(browserCertificate)).digest('hex');
  await testInfo.attach('conversational-spatiotemporal-browser-certificate.json', {
    body: Buffer.from(`${JSON.stringify(browserCertificate, null, 2)}\n`),
    contentType: 'application/json',
  });
  if (process.env.CONVERSATIONAL_SPATIOTEMPORAL_CERTIFICATE_PATH) {
    const target = resolve(process.env.CONVERSATIONAL_SPATIOTEMPORAL_CERTIFICATE_PATH);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, `${JSON.stringify(browserCertificate, null, 2)}\n`, 'utf8');
  }
  if (process.env.CONVERSATIONAL_SPATIOTEMPORAL_SCREENSHOT_PATH) {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.screenshot({
      path: resolve(process.env.CONVERSATIONAL_SPATIOTEMPORAL_SCREENSHOT_PATH),
      fullPage: true,
    });
  }
});
