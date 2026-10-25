import {test,expect,Page} from '@playwright/test';
import {authenticateBuyer} from './helpers/authenticatedTest';
import {supplierPanel} from './helpers/supplierPanel';
const tenant='synthetic-electronics';
const base='/api/v1/admin/inventory/supplier-enquiries';
const requester=process.env.DEVELOPER_API_KEY!,approver=process.env.OWNER_API_KEY!,alias=process.env.MERCHANT_API_KEY!;
async function panel(page:Page,key:string){
 await supplierPanel(page,key,tenant);
}

test('accepted shortfall connects to independent approval fake send and reviewed supplier replies',async({browser,baseURL},info)=>{
 test.setTimeout(150000);
 const buyerContext=await browser.newContext(),requestContext=await browser.newContext(),approveContext=await browser.newContext();
 await authenticateBuyer(buyerContext,baseURL!);
 const buyer=await buyerContext.newPage(),page=await requestContext.newPage(),review=await approveContext.newPage();
 const headers={'x-api-key':requester,'x-tenant-id':tenant};
 await buyer.goto('/?surface=qualified-shop');
 await buyer.getByRole('button',{name:'Start fictional buyer case'}).click();
 await buyer.getByLabel('Requested units').fill('30');
 let pending=buyer.waitForResponse(r=>r.url().includes('/stock-acceptance')&&r.request().method()==='POST');
 await buyer.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
 let response=await pending;expect(response.ok()).toBe(true);const accepted=await response.json();
 expect(accepted.shortfall).toBeGreaterThan(0);
 await panel(page,requester);await panel(review,approver);
 await page.getByLabel('Supplier case ID').fill(accepted.case_id);
 await page.getByLabel('Supplier case revision').fill(String(accepted.case_revision));
 await page.getByLabel('Enquiry reference').fill(`browser-rfq-${Date.now()}`);
 pending=page.waitForResponse(r=>r.url().endsWith('/supplier-enquiries')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'Draft shortfall enquiry'}).click();
 response=await pending;expect(response.ok(),await response.text()).toBe(true);const enquiry=await response.json();
 expect(enquiry.shortfall).toBe(accepted.shortfall);expect(enquiry.delivery_status).toBe('not_dispatched');
 await page.getByRole('button',{name:'Approve enquiry',exact:true}).click();
 await expect(page.getByRole('region',{name:'Supplier enquiries'}).getByRole('alert')).toContainText('distinct_people_required');
 const rejected=await requestContext.request.post(`${base}/${enquiry.id}/approve`,{headers:{...headers,'x-api-key':alias}});
 expect(rejected.status()).toBe(409);
 await review.getByLabel('Enquiry ID',{exact:true}).fill(enquiry.id);
 await review.getByRole('button',{name:'Load enquiry',exact:true}).click();
 await review.getByRole('button',{name:'Approve enquiry',exact:true}).click();
 await review.getByRole('button',{name:'Send through fake transport'}).click();
 const region=review.getByRole('region',{name:'Supplier enquiries'});
 await expect(region).toContainText('Delivery: sent. Transport attempts: 1.');
 await expect(region).toContainText('Silence is not acceptance.');
 const replay=await requestContext.request.post(`${base}/${enquiry.id}/dispatch`,{headers});expect(replay.ok()).toBe(true);
 expect((await replay.json()).transport_attempts).toBe(1);
 await review.getByText('Simulate a supplier reply',{exact:true}).click();
 for(const variant of ['partial','substitute','wrong_sender','expired','full']){
  const terms={sku:variant==='substitute'?'UNKNOWN-SUBSTITUTE':enquiry.sku,quantity:variant==='partial'?1:enquiry.shortfall,
   unit_cost_cents:70000,freight_cents:12000,currency:'AUD',lead_days:5,minimum_order:1,
   expires_at:new Date(Date.now()+(variant==='expired'?-60000:86400000)).toISOString()};
  const body={message_id:`browser-${enquiry.id}-${variant}`,sender_ref:variant==='wrong_sender'?'attacker':'fictional-distributor',terms};
  await review.getByLabel('Simulated supplier reply').fill(JSON.stringify(body));
  pending=review.waitForResponse(r=>r.url().endsWith('/simulated-replies')&&r.request().method()==='POST');
  await review.getByRole('button',{name:'Record simulated reply'}).click();
  response=await pending;expect(response.ok(),await response.text()).toBe(true);const reply=await response.json();
  const quote=review.getByTestId(`supplier-quote-${reply.id}`);
  if(['wrong_sender','expired'].includes(variant)){
   await expect(quote).toContainText('quarantined');await expect(quote.getByRole('button')).toBeDisabled();
  }else{
   await expect(quote).toContainText('review_required');await quote.getByRole('button').click();
   await expect(quote).toContainText('reviewed');
   await expect(quote).toContainText(variant==='substitute'?'substitute_unverified':variant);
  }
  const duplicate=await requestContext.request.post(`${base}/${enquiry.id}/simulated-replies`,{headers,data:body});
  expect(duplicate.ok()).toBe(true);expect((await duplicate.json()).id).toBe(reply.id);
 }
 const before=await (await requestContext.request.get(`${base}/${enquiry.id}`,{headers})).json();
 expect(before.quotes).toHaveLength(5);expect(before.transport_attempts).toBe(1);
 const full=before.quotes.find((q:any)=>q.assessment.coverage==='full'&&q.assessment.eligible);
 expect(full.assessment.landed_cost_cents).toBe(enquiry.shortfall*70000+12000);
 // An accepted amendment invalidates the old enquiry and quotes at consumption.
 await buyer.getByLabel('Requested units').fill('40');
 pending=buyer.waitForResponse(r=>r.url().includes('/stock-acceptance')&&r.request().method()==='POST');
 await buyer.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
 response=await pending;expect(response.ok()).toBe(true);const amended=await response.json();
 expect(amended.case_revision).toBeGreaterThan(accepted.case_revision);
 await review.getByRole('button',{name:'Load enquiry',exact:true}).click();
 await expect(region).toContainText('stale_case_revision');
 const blocked=await requestContext.request.post(`${base}/${enquiry.id}/dispatch`,{headers});expect(blocked.status()).toBe(409);
 const after=await (await requestContext.request.get(`${base}/${enquiry.id}`,{headers})).json();
 expect(after.quotes.every((q:any)=>!q.assessment.eligible)).toBe(true);expect(after.transport_attempts).toBe(1);
 await page.getByLabel('Supplier case revision').fill(String(amended.case_revision));
 await page.getByLabel('Enquiry reference').fill(`browser-amend-rfq-${Date.now()}`);
 pending=page.waitForResponse(r=>r.url().endsWith('/supplier-enquiries')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'Draft shortfall enquiry'}).click();
 response=await pending;expect(response.ok()).toBe(true);const next=await response.json();
 expect(next.requested_quantity).toBe(40);expect(next.shortfall).toBe(amended.shortfall);
 expect(next.value_cents*30).toBe(enquiry.value_cents*40);expect(next.approval_id).toBeNull();
 const noApproval=await requestContext.request.post(`${base}/${next.id}/dispatch`,{headers});expect(noApproval.status()).toBe(409);
 await review.getByLabel('Enquiry ID',{exact:true}).fill(next.id);
 await review.getByRole('button',{name:'Load enquiry',exact:true}).click();
 await review.getByRole('button',{name:'Approve enquiry',exact:true}).click();
 await review.getByRole('button',{name:'Send through fake transport'}).click();
 await expect(region).toContainText('Delivery: sent. Transport attempts: 1.');
 const revisedTerms={sku:next.sku,quantity:next.shortfall,unit_cost_cents:65000,freight_cents:18000,currency:'AUD',lead_days:7,minimum_order:1,expires_at:new Date(Date.now()+86400000).toISOString()};
 await review.getByText('Simulate a supplier reply',{exact:true}).click();
 await review.getByLabel('Simulated supplier reply').fill(JSON.stringify({message_id:`amend-${next.id}`,sender_ref:'fictional-distributor',terms:revisedTerms}));
 pending=review.waitForResponse(r=>r.url().endsWith('/simulated-replies')&&r.request().method()==='POST');
 await review.getByRole('button',{name:'Record simulated reply'}).click();
 response=await pending;expect(response.ok()).toBe(true);const revisedReply=await response.json();
 const revisedQuote=review.getByTestId(`supplier-quote-${revisedReply.id}`);
 await revisedQuote.getByRole('button').click();await expect(revisedQuote).toContainText('reviewed');
 await expect(revisedQuote).toContainText('Delivery: 7 days.');
 const revised=await (await requestContext.request.get(`${base}/${next.id}`,{headers})).json();
 expect(revised.approval_id).not.toBe(enquiry.approval_id);
 expect(revised.quotes[0].assessment.landed_cost_cents).toBe(next.shortfall*65000+18000);
 expect(revised.quotes[0].assessment.landed_cost_cents).toBeGreaterThan(full.assessment.landed_cost_cents);
 await info.attach('supplier-durable-state.json',{body:JSON.stringify({accepted,enquiry,before,amended,after,revised},null,2),contentType:'application/json'});
 // Release this demonstration's holds to keep reruns independent.
 const release=buyer.getByRole('button',{name:'Release simulated holds',exact:true});
 if(await release.isEnabled())await release.click();
 await buyerContext.close();await requestContext.close();await approveContext.close();
});
