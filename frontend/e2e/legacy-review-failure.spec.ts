import { expect, test } from '@playwright/test';

test.describe.configure({ retries: 0 });
test('failed requirement acceptance never becomes a completed review', async ({ page }) => {
  await page.route('**/api/v1/chat/stream', route => route.abort());
  await page.route('**/api/v1/chat/query', route => route.fulfill({ json: {
    shopping_case_id: 'case-review', shopping_case_retained_purpose: 'Laptop requirements',
    assistant_message: 'Review these case-only requirements.', products: [], next_questions: [],
    buyer_requirement_claims: [{ claim_id: 'claim-1', attribute: 'ram_gb', operator: '>=',
      value: 32, unit: 'GB', requirement_class: 'minimum', constraint_tier: 'hard',
      authority_status: 'case_origin_critic_accepted' }],
    buyer_requirement_proposal: { case_id: 'case-review', proposal_id: 'proposal-review', proposal_version: 1 },
  }}));
  await page.route('**/requirement-proposals/*/accept', route => route.fulfill({ status: 409,
    json: { detail: 'Review revision conflict' } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Ask Me!', exact: true }).click();
  await page.getByPlaceholder('Type your message...').fill('I need a laptop');
  await page.getByPlaceholder('Type your message...').press('Enter');
  const accept = page.getByRole('button', { name: 'Accept selected case evidence', exact: true });
  await accept.click();
  await expect(page.getByText('Review revision conflict', { exact: true })).toBeVisible();
  await expect(accept).toBeEnabled();
  await expect(page.getByText('Reviewed for provisional browsing.', { exact: true })).toHaveCount(0);
  let staleAccepts = 0;
  await page.route('**/requirement-proposals/*/accept', route => {
    staleAccepts++;
    return route.fulfill({ json: { status: 'unexpected' } });
  });
  await page.route('**/api/v1/chat/query', route => route.fulfill({ json: {
    terminal_outcome: {
      schema_version: 'turn-terminal-outcome-v1', operation_id: 'new-chair-operation',
      case_id: 'new-chair-case', case_revision: 1, products: [], next_questions: [],
      assistant_message: 'Current chair request', catalog_authority: 'blocked', commerce_authority: 'none',
    },
  }}));
  await page.getByPlaceholder('Type your message...').fill('Actually I need a chair');
  await page.getByPlaceholder('Type your message...').press('Enter');
  await expect(page.getByText('Current chair request', { exact: true })).toBeVisible();
  await accept.click();
  await expect(page.getByText('This review belongs to an earlier case. Use the current case review instead.', { exact: true })).toBeVisible();
  expect(staleAccepts).toBe(0);
});
