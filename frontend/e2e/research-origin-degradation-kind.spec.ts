import { expect, test } from '@playwright/test';

const profile = process.env.RESEARCH_DEGRADATION_PROFILE || '';
test.skip(
  !['publisher_timeout', 'zero_parser_yield'].includes(profile),
  'Requires one explicit Kind research certification fault profile.',
);

test(`${profile} remains honest, bounded, and offers buyer evidence fallback`, async ({ page }) => {
  test.setTimeout(120_000);
  const uid = `${profile}-${Date.now()}-${Math.random()}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need a laptop to simulate a PLC-controlled factory using Factory I/O.');
  await input.press('Enter');
  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible({ timeout: 45_000 });
  await expect(panel).toContainText(/external calls: 0/i);

  const responsePromise = page.waitForResponse(
    response => response.request().method() === 'POST'
      && /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(response.url()),
    { timeout: 90_000 },
  );
  await panel.getByRole('button', { name: 'Research approved sources' }).click();
  const response = await responsePromise;
  const payload = await response.json();
  expect(response.ok(), JSON.stringify(payload)).toBe(true);
  expect(payload.research.certification_fault_profile).toBe(profile);
  expect(payload.research.provider_accounting.paid_calls).toBe(0);
  expect(payload.research.claims).toHaveLength(0);
  expect(payload.research.context_claims).toHaveLength(0);
  expect(payload.evidence_outcome).toBe('unresolved');
  await expect(panel.getByRole('button', { name: 'Upload requirements' })).toBeVisible();
  await expect(page.getByText(/Authorized recommendation/i)).toHaveCount(0);

  if (profile === 'publisher_timeout') {
    const receipts = payload.research.receipts || [];
    expect(receipts.some((row: any) => row.fixture === true)).toBe(true);
    expect(receipts.some((row: any) => (
      row.rejection_reason === 'certification_injected_publisher_timeout'
    ))).toBe(true);
  } else {
    expect(payload.research.provider_accounting.official_origin_fetches).toBeGreaterThan(0);
    expect((payload.research.source_execution || []).every((row: any) => (
      row.parser_coverage?.parse_status === 'certification_injected_zero_parser_yield'
    ))).toBe(true);
  }
});
