import {test,expect,buyerUid} from './helpers/authenticatedTest';
import {turn} from './helpers/chatTurn';

test('ordinary chat exposes owned requirements and rejects stale or foreign selection',async({page,context})=>{
  await page.goto('/');
  await page.getByRole('button',{name:/Ask Me/i}).click({force:true});
  const first=await turn(page,'I need 1 laptop for Fictional Memory Lab version 1 for its memory capacity check only, under AUD 5000 per laptop.');
  const path=`/api/v1/shopping-cases/${encodeURIComponent(first.case_id)}/requirement-contract`;
  const initial=await context.request.get(path,{params:{uid:buyerUid}});
  expect(initial.ok()).toBe(true);
  const view=await initial.json();
  const contract=view.contracts.find((row:any)=>row.id==='fictional-memory-lab-v1');
  expect(contract).toBeTruthy();
  await page.getByLabel('Requirement scope').selectOption(contract.id);
  const saving=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().includes('/requirement-contract'));
  await page.getByRole('button',{name:'Select requirements',exact:true}).click();
  const saved=await saving;
  expect(saved.ok()).toBe(true);
  await expect(page.getByTestId('contract-state')).toHaveText('current');
  const selected=(await saved.json()).selection;
  const stale=await context.request.put(path,{data:{uid:buyerUid,
    expected_revision:view.selection.case_revision,contract_id:contract.id,
    contract_revision:contract.revision,context:contract.context}});
  expect(stale.status()).toBe(409);
  const foreign=await context.request.get(path,{params:{uid:'copied-foreign-buyer'}});
  expect(foreign.status()).toBe(403);
  const current=await context.request.get(path,{params:{uid:buyerUid}});
  expect((await current.json()).selection).toEqual(selected);
  expect(selected.fit_authority).toBe('none');
  expect(selected.commerce_authority).toBe('none');
});
