import {test,expect} from './helpers/ordinaryBuyerTest';
import {terminalTurn as turn} from './helpers/terminalTurn';
import {readChatResponse} from './helpers/chatTurn';
import {supplierPanel} from './helpers/supplierPanel';

test('catalogue buyer explicitly accepts stock and retains the exact shortage draft after reload',async({page,browser},info)=>{
  test.setTimeout(180000);
  const privileged:string[]=[];
  const externalEffects:string[]=[];
  page.on('request',request=>{
    const path=new URL(request.url()).pathname;
    if(path.startsWith('/api/v1/')&&request.headers()['x-api-key'])privileged.push(path);
    if(request.method()==='POST'&&/\/(?:dispatch|payments|orders)(?:\/|$)/.test(path))externalEffects.push(path);
  });
  await page.goto('/');await page.getByRole('button',{name:/Ask Me/i}).click();
  const choices=await turn(page,'Show me 40 laptops under AUD 1500 each. I am browsing the catalogue.');
  await info.attach('catalogue-entry.json',{body:JSON.stringify(choices,null,2),contentType:'application/json'});
  expect(choices.products.length).toBeGreaterThan(0);
  expect(choices.semantic_resolution.outcome).toBe('catalog_browse');
  const sku=choices.products[0].sku;
  await page.getByRole('button',{name:`Review simulated stock for ${sku}`,exact:true}).click();
  await expect(page.getByTestId('live-available')).toHaveText('15');
  await expect(page.getByLabel('Requested units')).toHaveValue('40');
  const accepting=page.waitForResponse(r=>r.url().endsWith('/stock-acceptance')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
  const acceptedResponse=await accepting;
  expect(acceptedResponse.ok(),await acceptedResponse.text()).toBe(true);
  const accepted=await acceptedResponse.json();
  expect([accepted.requested_quantity,accepted.held_quantity,accepted.shortfall]).toEqual([40,15,25]);
  await expect(page.getByTestId('accepted-stock')).toHaveText('Requested 40 · Held 15 · Shortfall 25');
  if(process.env.EXTERNAL_RESEARCH_ENABLED==='1'){
    expect(process.env.SEMANTIC_RESEARCH_FIXTURES_ENABLED).toBe('0');
    await page.getByPlaceholder('Type your message...').fill(
      'Check the official FreeCAD 1.0 requirements online for my current laptop request. Keep my quantity and budget.');
    await page.getByPlaceholder('Type your message...').press('Enter');
    const researching=page.waitForResponse(r=>r.request().method()==='POST'&&/\/api\/v1\/chat\/(stream|query)(?:\?|$)/.test(r.url()),{timeout:65000});
    await page.getByRole('button',{name:/Check approved sources/}).click();
    const researched=await readChatResponse(await researching);
    await info.attach('live-research-between-stock-and-draft.json',{body:JSON.stringify(researched,null,2),contentType:'application/json'});
    expect(researched.case_id).toBe(choices.case_id);
    expect(researched.retained_buyer_facts.requested_quantity).toBe(40);
    expect(researched.terminal_outcome.commerce_authority).toBe('none');
    const receipts:any[]=[];
    function visit(value:any){
      if(!value||typeof value!=='object')return;
      if(value.external_call_dispatched===true)receipts.push(value);
      for(const child of Object.values(value))visit(child);
    }
    visit(researched);
    expect(receipts.length,'live search needs a real dispatch receipt').toBeGreaterThan(0);
    expect(receipts.every(row=>row.fixture!==true)).toBe(true);
    // Research changes the case revision. A buyer must explicitly reaccept
    // stock on that revision; the earlier hold cannot authorize a stale draft.
    const reaccepting=page.waitForResponse(r=>r.url().endsWith('/stock-acceptance')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
    const reaccepted=await reaccepting;
    expect(reaccepted.ok(),await reaccepted.text()).toBe(true);
    expect((await reaccepted.json()).shortfall).toBe(25);
  }
  const draft=await turn(page,'Draft an email asking the supplier for the remaining unit shortfall. Do not send it.');
  expect(draft.case_id).toBe(choices.case_id);
  expect(draft.email_draft).toMatchObject({sku,requested_quantity:40,shortfall:25,dispatch_authorized:false});
  expect(draft.email_draft.body).toContain('25 units');
  expect(draft.email_draft.body).toContain('40 units');
  expect(draft.email_draft.draft_artifact.content_hash).toMatch(/^[a-f0-9]{64}$/);
  const authorContext=await browser.newContext(),reviewerContext=await browser.newContext();
  let savedDraft:any;
  try{
    const author=await authorContext.newPage(),reviewer=await reviewerContext.newPage();
    await supplierPanel(author,process.env.DEVELOPER_API_KEY!,'synthetic-electronics');
    await supplierPanel(reviewer,process.env.OWNER_API_KEY!,'synthetic-electronics');
    await author.getByLabel('Supplier case ID').fill(draft.case_id);
    await author.getByLabel('Supplier case revision').fill(String(draft.case_revision));
    await author.getByLabel('Enquiry reference').fill(`catalogue-draft-${Date.now()}`);
    const creating=author.waitForResponse(r=>r.url().endsWith('/supplier-enquiries')&&r.request().method()==='POST');
    await author.getByRole('button',{name:'Draft shortfall enquiry',exact:true}).click();
    const createdResponse=await creating;
    expect(createdResponse.ok(),await createdResponse.text()).toBe(true);
    const created=await createdResponse.json();
    expect(created.message.body).toBe(draft.email_draft.body);
    expect(created.draft_artifact.content_hash).toBe(draft.email_draft.draft_artifact.content_hash);
    await reviewer.getByLabel('Enquiry ID',{exact:true}).fill(created.id);
    await reviewer.getByRole('button',{name:'Load enquiry',exact:true}).click();
    await reviewer.getByRole('button',{name:'Approve enquiry',exact:true}).click();
    await expect(reviewer.getByRole('region',{name:'Supplier enquiries'})).toContainText('Approval: current.');
    await author.getByRole('button',{name:'Load enquiry',exact:true}).click();
    await author.getByLabel('Include buyer budget in supplier message').uncheck();
    await author.getByRole('button',{name:'Save revised draft for review',exact:true}).click();
    await expect(author.getByText('Draft version 2. Changes require fresh independent approval.')).toBeVisible();
    const preview=await turn(page,'Show the supplier email draft for my current request.');
    expect(preview.email_draft.draft_version).toBe(2);
    expect(preview.email_draft.dispatch_authorized).toBe(false);
    savedDraft=preview.email_draft;
    await info.attach('reviewed-revised-catalogue-draft.json',{body:JSON.stringify({created,preview},null,2),contentType:'application/json'});
  }finally{await authorContext.close();await reviewerContext.close();}
  const market=await turn(page,'What market intelligence answers supplier lead times for my current request?');
  expect(market.case_id).toBe(choices.case_id);
  expect(market.retained_buyer_facts.requested_quantity).toBe(40);
  if(market.market_intelligence.delivery_status==='available'){
    expect(market.market_intelligence.market_evidence.citations.length).toBeGreaterThan(0);
    expect(market.market_intelligence.unanswered_market_facets||[]).not.toContain('lead_time');
  }else{
    expect(['blocked','unavailable']).toContain(market.market_intelligence.delivery_status);
    expect(market.market_intelligence.delivery_reason).toBeTruthy();
  }
  await page.reload();
  if(!await page.getByPlaceholder('Type your message...').isVisible())await page.getByRole('button',{name:/Ask Me/i}).click();
  const restored=await turn(page,'Show the supplier email draft for my current request.');
  expect(restored.email_draft.draft_artifact).toEqual(savedDraft.draft_artifact);
  expect(restored.email_draft.draft_version).toBe(2);
  expect(restored.retained_buyer_facts.requested_quantity).toBe(40);
  expect(restored.terminal_outcome.commerce_authority).toBe('none');
  expect(privileged).toEqual([]);expect(externalEffects).toEqual([]);
  await info.attach('catalogue-shortfall-draft.json',{body:JSON.stringify({accepted,draft,market,restored},null,2),contentType:'application/json'});
  await info.attach('catalogue-shortfall-screen',{body:await page.screenshot({fullPage:true}),contentType:'image/png'});
});
