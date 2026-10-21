import {test,expect} from './helpers/authenticatedTest';
import {turn} from './helpers/chatTurn';
import {qualify,reviewCurrentFixtureStock} from './helpers/currentQualification';

test('a signed buyer without an operator API key retains the exact shortage draft',async({page,context},info)=>{
  test.setTimeout(240000);
  const tenant=process.env.VITE_STOREFRONT_TENANT_ID;
  await context.setExtraHTTPHeaders(tenant?{'x-tenant-id':tenant}:{});
  const privilegedRequests:string[]=[];
  page.on('request',request=>{
    if(request.url().includes('/api/v1/')&&request.headers()['x-api-key']){
      privilegedRequests.push(new URL(request.url()).pathname);
    }
  });
  const qualified=await qualify(page,context,info);
  await reviewCurrentFixtureStock(page,qualified);
  await page.getByLabel('Requested units').fill('40');
  const saving=page.waitForResponse(r=>r.url().endsWith('/stock-acceptance')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
  const saved=await saving;
  expect(saved.ok()).toBe(true);
  const accepted=await saved.json();
  expect([accepted.requested_quantity,accepted.held_quantity,accepted.shortfall]).toEqual([40,15,25]);
  const draft=await turn(page,'Draft an email to the supplier for the remaining stock shortfall in my current request.');
  expect(draft.case_id).toBe(qualified.case_id);
  expect(draft.email_draft).toMatchObject({requested_quantity:40,shortfall:25,dispatch_authorized:false});
  expect(draft.email_draft.body).toContain('25 units');
  await page.reload();
  await page.getByRole('button',{name:/Ask Me/i}).click({force:true});
  const restored=await turn(page,'Draft an email to the supplier for the remaining stock shortfall in my current request.');
  expect(restored.case_id).toBe(qualified.case_id);
  expect(restored.email_draft).toMatchObject({requested_quantity:40,shortfall:25,dispatch_authorized:false});
  expect(privilegedRequests,'Buyer requests must not carry an operator API key').toEqual([]);
});
