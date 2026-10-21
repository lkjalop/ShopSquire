import {expect,type Page,type BrowserContext,type TestInfo} from '@playwright/test';
import {turn,readChatResponse} from './chatTurn';
import {turnViolations} from './turnOracle';

export async function research(page:Page){
  await page.getByPlaceholder('Type your message...').fill('Search online for Fictional Memory Lab version 1 requirements and check a laptop against my selected memory capacity scope.');
  await page.getByPlaceholder('Type your message...').press('Enter');
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&/\/api\/v1\/chat\/(stream|query)(?:\?|$)/.test(r.url()),{timeout:65000});
  await page.getByRole('button',{name:/Check approved sources/}).click();
  return readChatResponse(await response);
}

export async function qualify(page:Page,context:BrowserContext,info:TestInfo){
  await page.goto('/');
  await page.getByRole('button',{name:/Ask Me/i}).click({force:true});
  const first=await turn(page,'I need 1 laptop for Fictional Memory Lab version 1 for its memory capacity check only, under AUD 5000 per laptop.');
  await info.attach('initial.json',{body:JSON.stringify(first,null,2),contentType:'application/json'});
  await page.getByLabel('Requirement scope').selectOption('fictional-memory-lab-v1');
  await page.getByRole('button',{name:'Select requirements',exact:true}).click();
  await expect(page.getByTestId('contract-state')).toHaveText('current');
  const result=await research(page);
  await info.attach('qualification.json',{body:JSON.stringify(result,null,2),contentType:'application/json'});
  expect(result.case_id).toBe(first.case_id);
  const shelves=result.product_shelves;
  expect(shelves,'the normal response must carry the evaluated shelf').toBeTruthy();
  const qualified=shelves.shelves.flatMap((s:any)=>[...s.initial,...s.next_page]).filter((p:any)=>p.fit_status==='qualified');
  expect(qualified.length).toBeGreaterThan(0);
  expect(shelves.requirement_contract.state).toBe('current');
  expect(shelves.requirement_contract.case_revision).toBe(result.case_revision);
  expect(turnViolations(result,{qualifiedDelivery:true,acceptedClaims:1})).toEqual([]);
  expect(result.assistant_message).toContain('fictional scope');
  expect(result.terminal_outcome.commerce_authority).toBe('none');
  await expect(page.getByText(result.assistant_message,{exact:true}).last()).toBeVisible();
  return result;
}

export async function reviewCurrentFixtureStock(page:Page,result:any){
  const sku=process.env.ROADMAP_QUALIFIED_BASE_SKU;
  expect(sku,'Prepare a current fictional fixture with its exact base SKU').toBeTruthy();
  const qualified=result.product_shelves.shelves.flatMap((s:any)=>[...s.initial,...s.next_page])
    .filter((p:any)=>p.fit_status==='qualified');
  expect(qualified.some((p:any)=>p.product.sku===sku),'the fixture SKU must qualify on this case revision').toBe(true);
  await page.getByRole('button',{name:`Review simulated stock for ${sku}`,exact:true}).click();
}
