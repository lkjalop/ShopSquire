import {test,expect,Page} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {authenticateBuyer} from './helpers/authenticatedTest';
const tenant='synthetic-electronics';
const base='/api/v1/admin/inventory/supplier-enquiries';
const requester=process.env.DEVELOPER_API_KEY!,approver=process.env.OWNER_API_KEY!;
async function panel(page:Page,key:string){
 await page.addInitScript(key=>{sessionStorage.setItem('auth_email','fixture@example.invalid');sessionStorage.setItem('role','owner');sessionStorage.setItem('ss_owner_key',key);},key);
 await page.goto('/');await page.getByRole('button',{name:'Dashboard',exact:true}).click();
 await page.getByRole('button',{name:'Supply Chain Health',exact:true}).click();
 await page.getByLabel('Supplier tenant').fill(tenant);
}

test('operator reconciles uncertain delivery and obtains fresh independent approval for one replacement',async({browser,baseURL},info)=>{
 test.setTimeout(150000);
 const bc=await browser.newContext(),rc=await browser.newContext(),ac=await browser.newContext();
 await authenticateBuyer(bc,baseURL!);
 const buyer=await bc.newPage(),requesterPage=await rc.newPage(),operator=await ac.newPage();
 const headers={'x-api-key':requester,'x-tenant-id':tenant};
 await buyer.goto('/?surface=qualified-shop');
 await buyer.getByRole('button',{name:'Start fictional buyer case'}).click();
 await buyer.getByLabel('Requested units').fill('30');
 let responsePromise=buyer.waitForResponse(r=>r.url().includes('/stock-acceptance')&&r.request().method()==='POST');
 await buyer.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
 const acceptance=await responsePromise;expect(acceptance.ok()).toBe(true);const accepted=await acceptance.json();
 const created=await rc.request.post(base,{headers,data:{case_id:accepted.case_id,expected_revision:accepted.case_revision,supplier_ref:'fictional-distributor',source_reference:`recovery-${Date.now()}`}});
 expect(created.ok(),await created.text()).toBe(true);const original=await created.json();
 await panel(requesterPage,requester);await panel(operator,approver);
 await operator.getByLabel('Enquiry ID',{exact:true}).fill(original.id);
 await operator.getByRole('button',{name:'Load enquiry',exact:true}).click();
 await operator.getByRole('button',{name:'Approve enquiry',exact:true}).click();
 await expect(operator.getByRole('region',{name:'Supplier enquiries'})).toContainText('Approval: current.');
 const root=process.env.ROADMAP_TEST_ROOT||process.cwd();
 execFileSync(process.env.ROADMAP_TEST_PYTHON||path.join(root,'.venv','Scripts','python.exe'),['-m','scripts.simulate_uncertain_supplier_send','--tenant',tenant,'--enquiry',original.id],{cwd:root,env:process.env,timeout:30000});
 await operator.getByRole('button',{name:'Load enquiry',exact:true}).click();
 const region=operator.getByRole('region',{name:'Supplier enquiries'});
 await expect(region).toContainText('Delivery: reconciliation_required. Transport attempts: 1.');
 await expect(operator.getByRole('button',{name:'Send through fake transport'})).toBeDisabled();
 const early=await rc.request.post(`${base}/${original.id}/renew`,{headers,data:{expected_revision:accepted.case_revision,reference:'replacement'}});
 expect(early.status()).toBe(409);expect(await early.text()).toContain('reconciliation_required');
 await operator.getByText('Review and recover enquiry',{exact:true}).click();
 await operator.getByLabel('Recovery evidence reference').fill('simulation:provider-ledger:no-delivery');
 await operator.getByRole('button',{name:'Record observed outcome'}).click();
 await expect(region).toContainText('Delivery: resolved_not_delivered. Transport attempts: 1.');
 await requesterPage.getByLabel('Enquiry ID',{exact:true}).fill(original.id);
 await requesterPage.getByRole('button',{name:'Load enquiry',exact:true}).click();
 await requesterPage.getByLabel('Supplier case revision').fill(String(accepted.case_revision));
 await requesterPage.getByText('Review and recover enquiry',{exact:true}).click();
 await requesterPage.getByLabel('Replacement reference').fill('replacement');
 responsePromise=requesterPage.waitForResponse(r=>r.url().endsWith('/renew')&&r.request().method()==='POST');
 await requesterPage.getByRole('button',{name:'Draft replacement enquiry'}).click();
 const replaced=await responsePromise;expect(replaced.ok(),await replaced.text()).toBe(true);const replacement=await replaced.json();
 expect(replacement.id).not.toBe(original.id);expect(replacement.approval_state).toBe('not_requested');
 await requesterPage.getByRole('button',{name:'Approve enquiry',exact:true}).click();
 await expect(requesterPage.getByRole('region',{name:'Supplier enquiries'}).getByRole('alert')).toContainText('distinct_people_required');
 await operator.getByLabel('Enquiry ID',{exact:true}).fill(replacement.id);
 await operator.getByRole('button',{name:'Load enquiry',exact:true}).click();
 await operator.getByRole('button',{name:'Approve enquiry',exact:true}).click();
 // Revoke is effective at the server even if another tab still has an enabled send button.
 await expect(region).toContainText('Approval: current.');
 await requesterPage.getByRole('button',{name:'Load enquiry',exact:true}).click();
 await requesterPage.getByRole('button',{name:'Revoke enquiry approval'}).click();
 await expect(requesterPage.getByRole('region',{name:'Supplier enquiries'})).toContainText('Approval: revoked.');
 const blocked=await ac.request.post(`${base}/${replacement.id}/dispatch`,{headers:{...headers,'x-api-key':approver}});
 expect(blocked.status()).toBe(409);
 const before=await (await rc.request.get(`${base}/${original.id}`,{headers})).json();
 const after=await (await rc.request.get(`${base}/${replacement.id}`,{headers})).json();
 expect(before.delivery_status).toBe('resolved_not_delivered');expect(before.transport_attempts).toBe(1);
 expect(after.delivery_status).toBe('not_dispatched');expect(after.transport_attempts).toBe(0);
 const duplicate=await rc.request.post(`${base}/${original.id}/renew`,{headers,data:{expected_revision:accepted.case_revision,reference:'different'}});
 expect(duplicate.status()).toBe(409);
 await info.attach('recovery-state.json',{body:JSON.stringify({before,after},null,2),contentType:'application/json'});
 const release=buyer.getByRole('button',{name:'Release simulated holds',exact:true});
 if(accepted.held_quantity>0){
  const released=buyer.waitForResponse(r=>r.url().endsWith('/release-holds')&&r.request().method()==='POST');
  await release.click();expect((await released).ok()).toBe(true);
 }else{
  await expect(release).toBeDisabled();
 }
 await bc.close();await rc.close();await ac.close();
});
