import {test,expect,buyerUid} from './helpers/authenticatedTest';

test('a failed cart clear stays visible and can recover without a false success',async({page})=>{
  const sku=process.env.ROADMAP_QUALIFIED_BASE_SKU;
  expect(sku,'prepare a shop with its exact laptop SKU').toBeTruthy();
  const seed=await page.request.put(`/api/v1/cart/items/${sku}`,{
    data:{uid:buyerUid,sku,quantity:2,allow_sourcing:true},
  });
  expect(seed.ok(),`cart seed HTTP ${seed.status()}`).toBeTruthy();
  await page.goto('/');
  await page.getByRole('button',{name:/Ask Me/i}).click();
  const clearPath=/\/api\/v1\/cart\/clear(?:\?|$)/;
  await page.route(clearPath,route=>route.fulfill({status:503,contentType:'application/json',
    body:JSON.stringify({detail:'cart_snapshot_unavailable'})}));
  const input=page.getByPlaceholder('Type your message...');
  const failed=page.waitForResponse(r=>clearPath.test(r.url())&&r.request().method()==='POST');
  await input.fill('Clear cart.');
  await input.press('Enter');
  expect((await failed).status()).toBe(503);
  await expect(page.getByText(/couldn't confirm that your cart was cleared/i)).toBeVisible();
  await expect(page.getByText(/your cart is now empty/i)).toHaveCount(0);
  const retained=await page.request.get(`/api/v1/cart?uid=${encodeURIComponent(buyerUid)}`);
  expect(retained.ok()).toBeTruthy();
  expect((await retained.json()).items).toEqual(expect.arrayContaining([expect.objectContaining({sku,quantity:2})]));
  await page.unroute(clearPath);
  const recovered=page.waitForResponse(r=>clearPath.test(r.url())&&r.request().method()==='POST');
  await input.fill('Clear cart.');
  await input.press('Enter');
  expect((await recovered).ok()).toBeTruthy();
  await expect(page.getByText(/your cart is now empty/i)).toBeVisible();
  const emptied=await page.request.get(`/api/v1/cart?uid=${encodeURIComponent(buyerUid)}`);
  expect(emptied.ok()).toBeTruthy();
  expect((await emptied.json()).items).toEqual([]);
});
