import {test,expect} from './helpers/authenticatedTest';
import {turn,readChatResponse} from './helpers/chatTurn';
import {execFileSync} from 'node:child_process';

test('consented live discovery preserves scope and grants no commerce authority',async({page},info)=>{
  test.setTimeout(180000);
  expect(process.env.EXTERNAL_RESEARCH_ENABLED).toBe('1');
  expect(process.env.SEMANTIC_RESEARCH_FIXTURES_ENABLED).toBe('0');
  const snapshot=()=>JSON.parse(execFileSync(process.env.ROADMAP_TEST_PYTHON!,['-m','scripts.demo_effect_snapshot'],
    {cwd:process.env.ROADMAP_TEST_ROOT,env:process.env,timeout:15000}).toString());
  await page.goto('/');await page.getByRole('button',{name:/Ask Me/i}).click();
  const before=snapshot();
  const first=await turn(page,'I need 3 laptops under AUD 2000 per laptop for FreeCAD 1.0 mechanical design.');
  await info.attach('before-consent.json',{body:JSON.stringify(first,null,2),contentType:'application/json'});
  await page.getByPlaceholder('Type your message...').fill('Search online for the official FreeCAD 1.0 requirements.');
  await page.getByPlaceholder('Type your message...').press('Enter');
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&/\/api\/v1\/chat\/(stream|query)(?:\?|$)/.test(r.url()),{timeout:65000});
  await page.getByRole('button',{name:/Check approved sources/}).click();
  const result=await readChatResponse(await response);
  await info.attach('live-research.json',{body:JSON.stringify(result,null,2),contentType:'application/json'});
  expect(result.case_id).toBe(first.case_id);
  expect(result.terminal_outcome.commerce_authority).toBe('none');
  expect(result.terminal_outcome.canonical_facts.budget_scope).toBe('per_unit');
  expect(result.terminal_outcome.canonical_facts.commercial_terms.currency).toBe('AUD');
  expect(snapshot()).toEqual(before);
  const receipts:any[]=[];
  function visit(value:any){
    if(!value||typeof value!=='object')return;
    if(value.external_call_dispatched===true)receipts.push(value);
    for(const child of Object.values(value))visit(child);
  }
  visit(result);
  expect(receipts.length,'a live claim requires an actual dispatch receipt').toBeGreaterThan(0);
  expect(receipts.every(row=>row.fixture!==true)).toBe(true);
  await expect(page.getByText(result.assistant_message,{exact:true}).last()).toBeVisible();
});
