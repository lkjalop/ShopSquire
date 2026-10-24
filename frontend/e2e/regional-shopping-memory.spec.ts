import {expect, test} from '@playwright/test';
import {registerBuyer} from './helpers/registeredBuyer';
import {terminalTurn as turn} from './helpers/terminalTurn';

for (const region of [
  {country:'Australia', currency:'AUD', city:'Sydney'},
  {country:'United States', currency:'USD', city:'Austin'},
  {country:'Germany', currency:'EUR', city:'Berlin'},
]) test(`${region.country}: currency, quantity and supplier draft survive correction and reload`, async ({page}, info) => {
  test.setTimeout(180000);
  await registerBuyer(page.context());
  const privileged:string[]=[];
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/v1/') && request.headers()['x-api-key']) privileged.push(request.url());
  });
  await page.goto('/');
  await page.getByRole('button',{name:/Ask Me/i}).click({force:true});
  const first=await turn(page,'I need 8 laptops with AUD 1200 per laptop.');
  await turn(page,`Deliver to ${region.city}.`);
  const amended=await turn(page,`Change my budget to 10,000 ${region.currency} total for all 8 laptops.`);
  expect(amended.case_id).toBe(first.case_id);
  expect(amended.retained_buyer_facts.requested_quantity).toBe(8);
  expect(amended.retained_buyer_facts.budget).toEqual({amount_minor:1000000,currency:region.currency,scope:'total'});
  const workload=await turn(page,'The workload is CAD work, with the same quantity and the same budget.');
  expect(workload.case_id).toBe(first.case_id);
  expect(workload.retained_buyer_facts.budget).toEqual(amended.retained_buyer_facts.budget);
  const draft=await turn(page,'Draft a supplier email for my current request. Do not send it.');
  expect(draft.email_draft.requested_quantity).toBe(8);
  expect(draft.email_draft.body).toContain(`${region.currency} 10000.00 total`);
  expect(draft.email_draft.body).toContain(region.city);
  expect(draft.email_draft.shortfall).toBeNull();
  expect(draft.email_draft.missing_inputs).toContain('current_accepted_selection');
  expect(draft.email_draft.dispatch_authorized).toBe(false);
  await page.reload();
  await page.getByRole('button',{name:/Ask Me/i}).click({force:true});
  const restored=await turn(page,'Summarise my quantity, budget and delivery destination.');
  expect(restored.case_id).toBe(first.case_id);
  expect(restored.retained_buyer_facts.budget).toEqual(amended.retained_buyer_facts.budget);
  expect(restored.retained_buyer_facts.requested_quantity).toBe(8);
  expect(restored.retained_buyer_facts.destinations[0]).toMatchObject({location_ref:region.city,quantity:8});
  expect(restored.terminal_outcome.commerce_authority).toBe('none');
  expect(privileged,'Ordinary buyers must not borrow operator credentials').toEqual([]);
  await info.attach('regional-summary',{body:JSON.stringify({region,amended,draft,restored}),contentType:'application/json'});
});
