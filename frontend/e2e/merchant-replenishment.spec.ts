import {test,expect} from '@playwright/test';
import {readFileSync} from 'fs';
import {resolve} from 'path';

function ownerKey(){
  if(process.env.OWNER_API_KEY)return process.env.OWNER_API_KEY;
  for(const file of ['frontend/.env.local','frontend/.env.development.local']){
    try{const found=readFileSync(resolve(file),'utf8').match(/^VITE_OWNER_API_KEY=(.*)$/m);if(found)return found[1].trim();}catch{/* next */}
  }
  return 'local-owner-key';
}

test('merchant reviews a persisted synthetic decision and wrong scope returns no data',async({page},info)=>{
  await page.addInitScript(key=>{
    sessionStorage.setItem('auth_email','operator@example.invalid');
    sessionStorage.setItem('auth_name','Synthetic operator');
    sessionStorage.setItem('role','owner');
    sessionStorage.setItem('ss_owner_key',key);
  },ownerKey());
  await page.goto('/');
  await page.getByRole('button',{name:'Dashboard',exact:true}).click();
  await page.getByRole('button',{name:'Supply Chain Health',exact:true}).click();
  await page.getByLabel('Decision tenant').fill('synthetic-market-pilot');
  await page.getByLabel('Decision SKU').fill('LAP-01B48B57');
  const pending=page.waitForResponse(r=>r.url().includes('/intelligence/replenishment/'));
  await page.getByRole('button',{name:'Review replenishment',exact:true}).click();
  const response=await pending;expect(response.ok()).toBe(true);
  const result=await response.json();
  await info.attach('decision.json',{body:JSON.stringify(result,null,2),contentType:'application/json'});
  expect(result.decision.status).toBe('advisory');
  expect(result.decision.commerce_authority).toBe('none');
  expect(result.covered_days).toBe(180);
  expect(result.evidence.status).toBe('retrieved');
  expect(result.evidence.retrieval.dense_provider).not.toBe('not_called');
  expect(result.evidence.commerce_authority).toBe('none');
  expect(result.evidence.hits.flatMap((hit:any)=>hit.claims)).toContainEqual({field:'lead_time',value:9,unit:'days',quote:'Delivery lead time is 9 days.'});
  await expect(page.getByText('Simulation only · Advisory · No purchase authorized',{exact:true})).toBeVisible();
  await expect(page.getByText(`Available: ${result.decision.available_units} units. Incoming: ${result.decision.incoming_units} units. Target: ${result.decision.target_units} units.`,{exact:true})).toBeVisible();
  await page.getByText('Source evidence',{exact:true}).click();
  await expect(page.getByText(result.quote.source_id,{exact:true}).first()).toBeVisible();
  await expect(page.getByRole('region',{name:'Reviewed market evidence'})).toContainText('Delivery lead time is 9 days.');
  await page.getByLabel('Decision SKU').fill('MISSING-SKU');
  await page.getByRole('button',{name:'Review replenishment',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveText('No decision dataset exists for this tenant and SKU.');
  await expect(page.getByText('Simulation only · Advisory · No purchase authorized',{exact:true})).toHaveCount(0);
  await page.getByLabel('Decision tenant').fill('synthetic-wrong-tenant');
  await page.getByLabel('Decision SKU').fill('LAP-01B48B57');
  await page.getByRole('button',{name:'Review replenishment',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveText('Decision unavailable (403).');
  const anonymous=await page.request.get('/api/v1/merchant/intelligence/replenishment/LAP-01B48B57');
  expect([401,403]).toContain(anonymous.status());
});
