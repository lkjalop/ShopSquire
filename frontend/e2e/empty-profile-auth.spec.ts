import {test, expect} from '@playwright/test';

test('ordinary registration and login permit own shopping but never operator approval access', async ({page, context}, info) => {
  const email = `browser-buyer-${Date.now()}@example.com`;
  const password = `BrowserOnly-${Date.now()}!`;
  await page.goto('/');
  expect((await context.cookies()).some(c => c.name === 'shopsquire_access')).toBe(false);
  await page.getByRole('button', {name:'Login', exact:true}).click();
  await page.getByRole('button', {name:'Register', exact:true}).click();
  await page.getByPlaceholder('Name', {exact:true}).fill('Fictional buyer');
  await page.getByPlaceholder('Email', {exact:true}).fill(email);
  await page.getByPlaceholder('Password', {exact:true}).fill(password);
  const registration = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/register') && r.request().method() === 'POST');
  await page.getByRole('button', {name:'Register', exact:true}).click();
  expect((await registration).ok()).toBe(true);
  await page.getByRole('button', {name:'Logout', exact:true}).click();
  await page.getByRole('button', {name:'Login', exact:true}).click();
  await page.getByPlaceholder('Email', {exact:true}).fill(email);
  await page.getByPlaceholder('Password', {exact:true}).fill(password);
  const login = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/login') && r.request().method() === 'POST');
  await page.getByPlaceholder('Password', {exact:true}).press('Enter');
  const loginResponse = await login;
  expect(loginResponse.ok()).toBe(true);
  const loginBody = await loginResponse.json();
  await expect(page.getByRole('button', {name:'Logout', exact:true})).toBeVisible();
  // Exercise the issued bearer credential as well as the browser cookie path;
  // an unwired cookie must not make a privileged token appear safe.
  const response = await context.request.get('/api/v1/approvals/pending', {
    headers: {Authorization: `Bearer ${loginBody.access_token}`},
  });
  // Never attach JWTs, passwords, cookies or other customers' approval payloads.
  await info.attach('buyer-operator-boundary.json', {body:JSON.stringify({status:response.status()}), contentType:'application/json'});
  expect([401,403], 'a public customer must not read the operator approval queue').toContain(response.status());
  const tenant = process.env.VITE_STOREFRONT_TENANT_ID;
  const cart = await context.request.get(`/api/v1/cart?uid=${encodeURIComponent(loginBody.user_id)}`, {
    headers: tenant ? {'x-tenant-id':tenant} : {},
  });
  expect.soft(cart.status(), 'native login must authenticate the buyer own-cart request').toBe(200);
  await page.getByRole('button', {name:/Ask Me/i}).click({force:true});
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('I need a laptop for university under AUD 1500.');
  const turn = page.waitForResponse(r => /\/api\/v1\/chat\/(query|stream)/.test(r.url()) && r.request().method() === 'POST');
  await input.press('Enter');
  const turnResponse = await turn;
  expect(turnResponse.status(), turnResponse.ok() ? 'native buyer chat' : await turnResponse.text()).toBe(200);
});
