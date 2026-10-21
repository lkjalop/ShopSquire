import {test,expect} from './helpers/authenticatedTest';
import {turn} from './helpers/chatTurn';
import {qualify,reviewCurrentFixtureStock} from './helpers/currentQualification';

test('ordinary signed-buyer requests retain their selected tenant without harness headers',async({page,context},info)=>{
  test.setTimeout(240000);
  const tenant=process.env.VITE_STOREFRONT_TENANT_ID;
  expect(tenant).toBeTruthy();
  expect(tenant).not.toBe('default');
  await context.setExtraHTTPHeaders({});
  const unscoped:string[]=[],privileged:string[]=[];
  page.on('request',request=>{
    const path=new URL(request.url()).pathname;
    if(!path.startsWith('/api/v1/'))return;
    if(request.headers()['x-api-key'])privileged.push(path);
    if(request.method()==='POST'&&/^\/api\/v1\/chat\/(query|stream)$/.test(path)
      &&request.headers()['x-tenant-id']!==tenant)unscoped.push(path);
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
  expect(privileged,'Browser requests must not carry an operator API key').toEqual([]);
  expect(unscoped,'Chat requests must carry the selected storefront tenant').toEqual([]);
});
