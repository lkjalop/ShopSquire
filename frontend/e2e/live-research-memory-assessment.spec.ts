import {test,expect} from './helpers/authenticatedTest';
import {turn,readChatResponse} from './helpers/chatTurn';
import {execFileSync} from 'node:child_process';

test('live research quantity correction supplier-draft request market question and reload retain scoped facts',async({page},info)=>{
  test.skip(process.env.EXTERNAL_RESEARCH_ENABLED !== '1', 'Requires an explicitly enabled read-only live research fixture');
  test.setTimeout(300000);
  const snapshot=()=>JSON.parse(execFileSync(process.env.ROADMAP_TEST_PYTHON!,['-m','scripts.demo_effect_snapshot'],
    {cwd:process.env.ROADMAP_TEST_ROOT,env:process.env,timeout:15000}).toString());
  const initial=snapshot();
  await page.goto('/');await page.getByRole('button',{name:/Ask Me/i}).click();
  const results:any[]=[];
  const first=await turn(page,'I need 30 laptops under AUD 1500 per laptop for FreeCAD 1.0 mechanical design. Deliver to Sydney.');
  results.push({query:'initial',response:first});
  await page.getByPlaceholder('Type your message...').fill('Search online for the official FreeCAD 1.0 requirements.');
  await page.getByPlaceholder('Type your message...').press('Enter');
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&/\/api\/v1\/chat\/(stream|query)(?:\?|$)/.test(r.url()),{timeout:65000});
  await page.getByRole('button',{name:/Check approved sources/}).click();
  const searched=await readChatResponse(await response);results.push({query:'consented search',response:searched});
  const before=snapshot();
  await info.attach('initial-effect-snapshot.json',{body:JSON.stringify({initial,before_advisory_turns:before}),contentType:'application/json'});
  expect.soft(searched.case_id,'search case').toBe(first.case_id);
  const queries=[
    'Actually make that 40 laptops. Keep my AUD 1500 per laptop budget and Sydney destination.',
    'Draft an email asking our supplier to quote the unit quantity shortfall. Do not send it.',
    'What market intelligence do you have on lead times and laptop supply? Keep my current request.',
    'Summarise my quantity, per-unit budget and delivery destination without taking any action.',
  ];
  for(const query of queries){
    const priorRevision=results.at(-1)?.response?.case_revision;
    const result=await turn(page,query);results.push({query,response:result});
    expect.soft(result.case_id,query+' case').toBe(first.case_id);
    expect.soft(result.retained_buyer_facts?.requested_quantity,query+' quantity').toBe(40);
    expect.soft(result.retained_buyer_facts?.budget,query+' budget').toEqual({amount_minor:150000,currency:'AUD',scope:'per_unit'});
    expect.soft(result.terminal_outcome.commerce_authority,query+' authority').toBe('none');
    if(query.startsWith('Draft an email')){
      expect(result.read_only_case_task).toBe(true);
      expect(result.case_revision).toBe(priorRevision);
      expect(result.email_draft).toMatchObject({case_id:first.case_id,requested_quantity:40,
        dispatch_authorized:false,commerce_authority:'none'});
      expect(result.email_draft.body).toContain('40 units');
      expect(result.email_draft.body).toContain('Sydney');
      if(result.email_draft.shortfall===null)expect(result.email_draft.missing_inputs.length).toBeGreaterThan(0);
      await expect(page.getByText(/Draft — choose a supplier contact before sending/).last()).toBeVisible();
    }
    if(query.includes('market intelligence')){
      expect(result.read_only_case_task).toBe(true);
      expect(result.case_revision).toBe(priorRevision);
      expect(result.market_intelligence.case_id).toBe(first.case_id);
      if(result.market_intelligence.delivery_status==='available'){
        expect(result.market_intelligence.market_evidence.citations.length).toBeGreaterThan(0);
      }else{
        expect(['blocked','unavailable']).toContain(result.market_intelligence.delivery_status);
        expect(result.market_intelligence.delivery_reason).toBeTruthy();
      }
    }
  }
  await page.reload();
  if(!await page.getByPlaceholder('Type your message...').isVisible())await page.getByRole('button',{name:/Ask Me/i}).click();
  const recalled=await turn(page,'How many laptops did I ask for and what was my budget and delivery destination?');
  results.push({query:'recall after reload',response:recalled});
  expect.soft(recalled.case_id).toBe(first.case_id);
  expect.soft(recalled.retained_buyer_facts?.requested_quantity).toBe(40);
  expect.soft(recalled.retained_buyer_facts?.destinations?.[0]?.location_ref).toBe('Sydney');
  expect.soft(snapshot(),'draft and advisory requests must not create commercial effects').toEqual(before);
  const draft = results.find(row => row.query.includes('Draft an email'))?.response;
  const market = results.find(row => row.query.includes('market intelligence'))?.response;
  await info.attach('task-completion-assessment.json',{body:JSON.stringify({
    email_draft: draft?.email_draft || null, email_reply: draft?.assistant_message,
    market_evidence: market?.market_intelligence || market?.decision_intelligence || null,
    market_reply: market?.assistant_message,
    scope:'Draft delivery is asserted. Market delivery requires current citations or an explicit blocked/unavailable reason; this does not certify live market-source freshness.'
  },null,2),contentType:'application/json'});
  await info.attach('cross-intent-memory.json',{body:JSON.stringify(results,null,2),contentType:'application/json'});
  await info.attach('cross-intent-screenshot',{body:await page.screenshot({fullPage:true}),contentType:'image/png'});
});
