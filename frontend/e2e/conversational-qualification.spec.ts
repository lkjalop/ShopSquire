import {test,expect,buyerUid} from './helpers/authenticatedTest';
import {readFile,writeFile} from 'node:fs/promises';
import {research,qualify,reviewCurrentFixtureStock} from './helpers/currentQualification';

test('ordinary chat qualifies fictional evidence with trace agreement and revocation',async({page,context},info)=>{
  test.setTimeout(180000);
  const result=await qualify(page,context,info);
  await page.getByTitle('Decision Trace',{exact:true}).click();
  const trace=page.getByTestId('decision-trace-modal');
  await expect(trace).toHaveAttribute('aria-modal','false');
  expect(await trace.evaluate(node=>node.contains(document.activeElement))).toBe(true);
  await expect(trace.getByTestId('revision-bound-turn-projection')).toContainText(`Case revision ${result.case_revision}`);
  await expect(trace.getByTestId('revision-bound-research-outcome')).toContainText('1 accepted, 0 held');
  await page.keyboard.press('Escape');
  await expect(trace).toBeHidden();
  await expect(page.getByTitle('Decision Trace',{exact:true})).toBeFocused();
  await page.getByRole('button',{name:'Revoke selection',exact:true}).click();
  await expect(page.getByTestId('contract-state')).toHaveText('revoked');
  const blocked=await research(page);
  await info.attach('revoked.json',{body:JSON.stringify(blocked,null,2),contentType:'application/json'});
  expect(blocked.requirement_contract.state).toBe('revoked');
  expect(blocked.product_shelves?.shelves?.flatMap((s:any)=>s.initial).some((p:any)=>p.fit_status==='qualified')??false).toBe(false);
  expect(blocked.terminal_outcome.commerce_authority).toBe('none');
});

for(const fault of ['expired','conflicting','revoked-source'])test(`normal chat rejects ${fault} evidence when consumed`,async({page,context},info)=>{
  test.setTimeout(180000);
  await qualify(page,context,info);
  const path=process.env.SEMANTIC_RESEARCH_FIXTURE_PATH!;
  const original=await readFile(path,'utf8');
  const fixture=JSON.parse(original);
  if(fault==='expired')fixture.claims[0].observed_at='2000-01-01T00:00:00+00:00';
  if(fault==='revoked-source')fixture.claims[0].revoked_at=new Date().toISOString();
  if(fault==='conflicting')fixture.claims.push({...fixture.claims[0],claim_id:'conflicting',value:64});
  try{
    await writeFile(path,JSON.stringify(fixture),'utf8');
    const result=await research(page);
    await info.attach(`${fault}.json`,{body:JSON.stringify(result,null,2),contentType:'application/json'});
    expect(result.semantic_requirement_compilation?.contract_coverage?.compiled_complete??false).toBe(false);
    expect(result.product_shelves?.shelves?.flatMap((s:any)=>s.initial).some((p:any)=>p.fit_status==='qualified')??false).toBe(false);
    expect(result.terminal_outcome.commerce_authority).toBe('none');
  }finally{await writeFile(path,original,'utf8');}
});

test('ordinary qualified case offers an evidenced accessory and changes the draft only after acceptance',async({page,context},info)=>{
  test.setTimeout(180000);
  const qualified=await qualify(page,context,info);
  await reviewCurrentFixtureStock(page,qualified);
  const options=page.getByRole('region',{name:'Supported product options'});
  await options.getByLabel('Case offer units').fill('2');
  const proposed=page.waitForResponse(r=>r.url().endsWith('/product-offers')&&r.request().method()==='POST');
  await options.getByRole('button',{name:'Review option HDD-3A5E65F1'}).click();
  const response=await proposed;expect(response.ok(),await response.text()).toBe(true);const offer=await response.json();
  const review=page.getByRole('region',{name:'Case product offer review'});
  await expect(review).toContainText('compatibility is invented');
  await expect(review).toContainText(`Total: AUD ${(offer.total_cents/100).toFixed(2)}`);
  const headers={'x-tenant-id':'synthetic-electronics'};
  const uid=await page.evaluate(()=>sessionStorage.getItem('uid'));
  const cartBefore=await (await page.request.get(`/api/v1/cart?uid=${encodeURIComponent(uid!)}`,{headers})).json();
  expect(cartBefore.items).toHaveLength(0);
  const accepted=page.waitForResponse(r=>r.url().endsWith(`/${offer.id}/accept`)&&r.request().method()==='POST');
  await review.getByRole('button',{name:'Accept exact case offer'}).click();
  const receiptResponse=await accepted;expect(receiptResponse.ok(),await receiptResponse.text()).toBe(true);
  const receipt=await receiptResponse.json();expect(receipt.case_revision).toBeGreaterThan(qualified.case_revision);
  await expect(page.getByTestId('contract-state')).toHaveText('stale_case_revision');
  const cartAfter=await (await page.request.get(`/api/v1/cart?uid=${encodeURIComponent(uid!)}`,{headers})).json();
  expect(cartAfter.items).toHaveLength(2);
  expect(cartAfter.bundle_savings.final_total_cents).toBe(offer.total_cents);
  const replay=await page.request.post(`/api/v1/shopping-cases/${qualified.case_id}/product-offers/${offer.id}/accept`,{headers,data:{uid}});
  expect(replay.ok()).toBe(true);expect(await replay.json()).toEqual(receipt);
  await info.attach('ordinary-case-bundle.json',{body:JSON.stringify({offer,receipt,cartBefore,cartAfter},null,2),contentType:'application/json'});
});

test('ordinary qualified case connects to accepted holds and an independently approved fake supplier conversation',async({page,context,browser},info)=>{
  test.setTimeout(240000);
  const qualified=await qualify(page,context,info);
  await reviewCurrentFixtureStock(page,qualified);
  await page.getByLabel('Requested units').fill('30');
  const acceptance=page.waitForResponse(r=>r.url().endsWith('/stock-acceptance')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
  const response=await acceptance;expect(response.ok(),await response.text()).toBe(true);
  const accepted=await response.json();
  expect(accepted.case_id).toBe(qualified.case_id);
  expect(accepted.held_quantity).toBe(15);expect(accepted.shortfall).toBe(15);
  await expect(page.getByTestId('accepted-stock')).toContainText('Requested 30');
  await expect(page.getByTestId('contract-state')).toHaveText('stale_case_revision');
  const requestContext=await browser.newContext(),approveContext=await browser.newContext();
  try{
    const requester=await requestContext.newPage(),approver=await approveContext.newPage();
    for(const [operator,key] of [[requester,process.env.DEVELOPER_API_KEY!],[approver,process.env.OWNER_API_KEY!]] as const){
      await operator.addInitScript(key=>{sessionStorage.setItem('auth_email','fixture@example.invalid');sessionStorage.setItem('role','owner');sessionStorage.setItem('ss_owner_key',key)},key);
      await operator.goto('/');await operator.getByRole('button',{name:'Dashboard',exact:true}).click();
      await operator.getByRole('button',{name:'Supply Chain Health',exact:true}).click();
      await operator.getByLabel('Supplier tenant').fill('synthetic-electronics');
    }
    await requester.getByLabel('Supplier case ID').fill(accepted.case_id);
    await requester.getByLabel('Supplier case revision').fill(String(accepted.case_revision));
    await requester.getByLabel('Enquiry reference').fill(`normal-case-${accepted.case_id}`);
    const draft=requester.waitForResponse(r=>r.url().endsWith('/supplier-enquiries')&&r.request().method()==='POST');
    await requester.getByRole('button',{name:'Draft shortfall enquiry'}).click();
    const draftResponse=await draft;expect(draftResponse.ok(),await draftResponse.text()).toBe(true);
    const enquiry=await draftResponse.json();
    expect(enquiry.shortfall).toBe(15);expect(enquiry.case_id).toBe(qualified.case_id);
    await requester.getByRole('button',{name:'Approve enquiry',exact:true}).click();
    await expect(requester.getByRole('region',{name:'Supplier enquiries'}).getByRole('alert')).toContainText('distinct_people_required');
    await approver.getByLabel('Enquiry ID',{exact:true}).fill(enquiry.id);
    await approver.getByRole('button',{name:'Load enquiry',exact:true}).click();
    await approver.getByRole('button',{name:'Approve enquiry',exact:true}).click();
    await approver.getByRole('button',{name:'Send through fake transport'}).click();
    await expect(approver.getByRole('region',{name:'Supplier enquiries'})).toContainText('Delivery: sent. Transport attempts: 1.');
    await approver.getByText('Simulate a supplier reply',{exact:true}).click();
    await approver.getByLabel('Simulated supplier reply').fill(JSON.stringify({message_id:`normal-reply-${enquiry.id}`,sender_ref:'fictional-distributor',
      terms:{sku:enquiry.sku,quantity:10,unit_cost_cents:70000,freight_cents:12000,currency:'AUD',lead_days:5,minimum_order:1,expires_at:new Date(Date.now()+86400000).toISOString()}}));
    const replyResponse=approver.waitForResponse(r=>r.url().endsWith('/simulated-replies')&&r.request().method()==='POST');
    await approver.getByRole('button',{name:'Record simulated reply'}).click();
    const reply=await (await replyResponse).json();
    const quote=approver.getByTestId(`supplier-quote-${reply.id}`);
    await quote.getByRole('button').click();await expect(quote).toContainText('reviewed');
    await expect(quote).toContainText('partial');await expect(quote).toContainText('7120.00');
    const buyerReply=page.waitForResponse(r=>r.url().includes('/supplier-quotes?')&&r.request().method()==='GET');
    await page.getByRole('button',{name:'Refresh supplier quotes',exact:true}).click();
    const buyerView=await (await buyerReply).json();
    expect(JSON.stringify(buyerView)).not.toContain('unit_cost_cents');
    const buyerQuote=buyerView.quotes.find((q:any)=>q.quote_id===reply.id);
    expect(buyerQuote.quantity).toBe(10);expect(buyerQuote.uncovered_quantity).toBe(5);
    expect(buyerQuote.total_price_cents).toBe(buyerQuote.unit_price_cents*10+12000);
    const buyerCard=page.getByTestId(`buyer-supplier-quote-${reply.id}`);
    await expect(buyerCard).toContainText('Remaining shortfall: 5');
    await expect(buyerCard).toContainText('Supplier-sourced subtotal:');
    const selectedResponse=page.waitForResponse(r=>r.url().endsWith('/supplier-quote-selection')&&r.request().method()==='POST');
    await buyerCard.getByRole('button',{name:'Select this sourcing estimate',exact:true}).click();
    const selected=await selectedResponse;expect(selected.ok(),await selected.text()).toBe(true);
    const selection=await selected.json();expect(selection.commerce_authority).toBe('none');
    expect(selection.quote.quote_id).toBe(reply.id);expect(selection.quote.uncovered_quantity).toBe(5);
    await expect(page.getByRole('region',{name:'Reviewed supplier options'})).toContainText('Sourcing estimate selected for operator review');
    const persisted=await page.request.get(`/api/v1/shopping-cases/${accepted.case_id}/supplier-quote-selection?uid=${buyerUid}`,{headers:{'x-tenant-id':'synthetic-electronics'}});
    expect(persisted.ok(),await persisted.text()).toBe(true);
    expect((await persisted.json()).selection_id).toBe(selection.selection_id);
    await page.getByLabel('Requested units').fill('40');
    const amended=page.waitForResponse(r=>r.url().endsWith('/stock-acceptance')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
    expect((await amended).ok()).toBe(true);
    await expect(buyerCard).toContainText('stale_case_revision');
    await expect(buyerCard).not.toContainText('Supplier-sourced subtotal:');
    await expect(page.getByRole('region',{name:'Reviewed supplier options'})).toContainText('previous selection is no longer current');
    await info.attach('normal-case-procurement.json',{body:JSON.stringify({accepted,enquiry,reply,selection},null,2),contentType:'application/json'});
  }finally{await requestContext.close();await approveContext.close();}
});
