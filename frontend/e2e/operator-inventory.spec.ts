import {test,expect,Page} from '@playwright/test';
import {authenticateBuyer} from './helpers/authenticatedTest';

const tenant='synthetic-inventory-ops',sku='LAP-01B48B57';
const base='/api/v1/admin/inventory';
const requester=process.env.DEVELOPER_API_KEY||'local-developer-key';
const approver=process.env.OWNER_API_KEY||'local-owner-key';
const alias=process.env.MERCHANT_API_KEY||'local-merchant-key';
async function openPanel(page:Page,key:string,scope=tenant,product=sku){
  await page.addInitScript(key=>{
    sessionStorage.setItem('auth_email','fixture@example.invalid');
    sessionStorage.setItem('auth_name','Fictional operator');
    sessionStorage.setItem('role','owner');
    sessionStorage.setItem('ss_owner_key',key);
  },key);
  await page.goto('/');
  await page.getByRole('button',{name:'Dashboard',exact:true}).click();
  await page.getByRole('button',{name:'Supply Chain Health',exact:true}).click();
  await page.getByLabel('Inventory tenant').fill(scope);
  await page.getByLabel('Inventory SKU').fill(product);
}

test('independent people receive and transfer stock exactly once through real API and UI',async({browser},info)=>{
  const first=await browser.newContext(),second=await browser.newContext();
  const page=await first.newPage(),review=await second.newPage();
  const headers={'x-api-key':requester,'x-tenant-id':tenant};
  const stock=async()=>{
    const response=await first.request.get(`${base}/operation-stock/${sku}`,{headers});
    expect(response.ok()).toBe(true);return response.json();
  };
  await openPanel(page,requester);await openPanel(review,approver);
  const before=await stock();
  for(const kind of ['receive','transfer']){
    await page.getByLabel('Inventory operation',{exact:true}).selectOption(kind);
    if(kind==='transfer')await page.getByLabel('Source location',{exact:true}).fill('warehouse');
    await page.getByLabel('Destination location',{exact:true}).fill(kind==='receive'?'warehouse':'store-b');
    await page.getByLabel('Movement quantity').fill(kind==='receive'?'3':'2');
    await page.getByLabel('Movement reference').fill(`browser:${kind}:${Date.now()}`);
    const pending=page.waitForResponse(r=>r.url().endsWith('/inventory/operations')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'Request movement',exact:true}).click();
    const created=await pending;expect(created.ok()).toBe(true);const row=await created.json();
    expect(row.value_cents).toBeGreaterThan(0);expect(row.simulation_only).toBe(true);
    const held=await stock();
    const premature=await first.request.post(`${base}/operations/${row.id}/execute`,{headers});
    expect(premature.status()).toBe(409);
    await page.getByRole('button',{name:'Approve movement',exact:true}).click();
    await expect(page.getByRole('alert')).toHaveText('A different enrolled person must approve this request.');
    const alternate=await first.request.post(`${base}/operations/${row.id}/approve`,{headers:{...headers,'x-api-key':alias}});
    expect(alternate.status()).toBe(409);expect((await alternate.json()).detail).toBe('distinct_people_required');
    expect((await stock()).movement_count).toBe(held.movement_count);
    await review.getByLabel('Inventory request ID').fill(row.id);
    await review.getByRole('button',{name:'Load request',exact:true}).click();
    await review.getByRole('button',{name:'Approve movement',exact:true}).click();
    await expect(review.getByRole('button',{name:'Execute approved movement',exact:true})).toBeEnabled();
    await review.getByRole('button',{name:'Execute approved movement',exact:true}).click();
    await expect(review.getByText(`Request ${row.id}`,{exact:false})).toContainText('completed');
    const replay=await first.request.post(`${base}/operations/${row.id}/execute`,{headers});
    expect(replay.ok()).toBe(true);
    expect((await stock()).movement_count).toBe(held.movement_count+1);
  }
  const after=await stock();expect(after.reconciliation.consistent).toBe(true);
  const at=(s:any,id:string)=>s.locations.find((r:any)=>r.location_id===id).on_hand;
  expect(at(after,'warehouse')).toBe(at(before,'warehouse')+1);
  expect(at(after,'store-b')).toBe(at(before,'store-b')+2);
  expect(after.movement_count).toBe(before.movement_count+2);
  await review.reload();
  const denied=await first.request.get(`${base}/operation-stock/${sku}`,{headers:{...headers,'x-tenant-id':'synthetic-other'}});
  expect([403,404]).toContain(denied.status());
  const anonymous=await first.request.post(`${base}/operations`,{data:{kind:'receive'}});
  expect([401,403]).toContain(anonymous.status());
  await info.attach('durable-inventory.json',{body:JSON.stringify({before,after},null,2),contentType:'application/json'});
  await first.close();await second.close();
});

test('accepted buyer holds connect to approved shipping returns and cancellation',async({browser,baseURL},info)=>{
  const buyerContext=await browser.newContext(),requestContext=await browser.newContext(),approveContext=await browser.newContext();
  await authenticateBuyer(buyerContext,baseURL!);
  const buyer=await buyerContext.newPage(),page=await requestContext.newPage(),review=await approveContext.newPage();
  const scope='synthetic-electronics',product='LAP-0A1191AB';
  const headers={'x-api-key':requester,'x-tenant-id':scope};
  const stock=async()=>{const r=await requestContext.request.get(`${base}/operation-stock/${product}`,{headers});expect(r.ok()).toBe(true);return r.json();};
  await openPanel(page,requester,scope,product);await openPanel(review,approver,scope,product);
  const before=await stock();
  let expectedEvents=0;
  async function acceptBuyer(){
    await buyer.goto('/?surface=qualified-shop');
    await buyer.getByRole('button',{name:'Start fictional buyer case'}).click();
    await buyer.getByLabel('Requested units').fill('2');
    const pending=buyer.waitForResponse(r=>r.url().includes('/stock-acceptance')&&r.request().method()==='POST');
    await buyer.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
    const response=await pending;expect(response.ok()).toBe(true);
    const accepted=await response.json();
    const held=(await stock()).reservations.filter((r:any)=>r.case_id===accepted.case_id&&r.selection_revision===accepted.case_revision&&r.status==='reserved');
    expectedEvents+=held.length;
    return accepted;
  }
  async function action(kind:string,accepted:any,qty:number){
    const current=await stock();
    const reservations=current.reservations.filter((r:any)=>r.case_id===accepted.case_id&&r.selection_revision===accepted.case_revision);
    let remaining=qty;
    for(const reservation of reservations){
      const available=kind==='return'
        ?(reservation.status==='shipped'?reservation.quantity-reservation.returned_quantity:0)
        :(reservation.status==='reserved'?reservation.quantity:0);
      const movement=Math.min(remaining,available);
      if(movement<=0)continue;
      if(kind==='cancel')expect(movement).toBe(reservation.quantity);
    await page.getByLabel('Inventory operation',{exact:true}).selectOption(kind);
    await page.getByLabel('Reservation ID',{exact:true}).fill(reservation.reservation_id);
    await page.getByLabel('Inventory case ID').fill(accepted.case_id);
    await page.getByLabel('Inventory case revision').fill(String(accepted.case_revision));
    await page.getByLabel('Movement quantity').fill(String(movement));
    await page.getByLabel('Movement reference').fill(`${kind}:${Date.now()}`);
    const pending=page.waitForResponse(r=>r.url().endsWith('/inventory/operations')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'Request movement',exact:true}).click();
    const response=await pending;expect(response.ok(),await response.text()).toBe(true);const row=await response.json();
    await review.getByLabel('Inventory request ID').fill(row.id);
    await review.getByRole('button',{name:'Load request',exact:true}).click();
    await review.getByRole('button',{name:'Approve movement',exact:true}).click();
    await review.getByRole('button',{name:'Execute approved movement',exact:true}).click();
    await expect(review.getByText(`Request ${row.id}`,{exact:false})).toContainText('completed');
    const replay=await requestContext.request.post(`${base}/operations/${row.id}/execute`,{headers});expect(replay.ok()).toBe(true);
    await buyer.getByRole('button',{name:'Refresh stock',exact:true}).click();
      expectedEvents++;
      remaining-=movement;
      if(remaining===0)break;
    }
    expect(remaining,'all requested units must have a valid allocation').toBe(0);
  }
  const accepted=await acceptBuyer();expect(accepted.held_quantity).toBe(2);
  await action('ship',accepted,2);
  await expect(buyer.getByTestId('stock-lifecycle')).toContainText('Shipped 2');
  await expect(buyer.getByTestId('accepted-stock')).toContainText('Shortfall 0');
  await action('return',accepted,1);
  await expect(buyer.getByTestId('stock-lifecycle')).toContainText('Returned 1');
  // A separate buyer case exercises cancellation without amending shipped stock.
  await buyer.evaluate(()=>sessionStorage.clear());
  const next=await acceptBuyer();await action('cancel',next,2);
  await expect(buyer.getByTestId('accepted-stock')).toContainText('Held 0');
  const after=await stock();expect(after.reconciliation.consistent).toBe(true);
  const total=(s:any)=>s.locations.reduce((n:number,r:any)=>n+r.on_hand,0);
  expect(total(after)).toBe(total(before)-1);
  expect(after.reservation_event_count).toBe(before.reservation_event_count+expectedEvents);
  await info.attach('buyer-order-effects.json',{body:JSON.stringify({before,after},null,2),contentType:'application/json'});
  await buyerContext.close();await requestContext.close();await approveContext.close();
});
