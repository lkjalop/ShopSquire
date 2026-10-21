import {test,expect,buyerUid} from './helpers/authenticatedTest';

test('clearing a real two-line cart immediately offers an exact one-time restore',async({page})=>{
  const catalog=await page.request.get('/api/v1/products/list?per_page=100');
  expect(catalog.ok()).toBeTruthy();
  const skus=(await catalog.json()).products.map((p:{sku:string})=>p.sku)
    .filter((sku:string)=>sku.startsWith('LAP-')).slice(0,2);
  expect(skus).toHaveLength(2);
  const lines=skus.map((sku:string,index:number)=>({sku,quantity:index+1}));
  for(const line of lines){
    const response=await page.request.put(`/api/v1/cart/items/${line.sku}`,{
      data:{uid:buyerUid,...line,allow_sourcing:true},
    });
    expect(response.ok(),`cart seed HTTP ${response.status()}`).toBeTruthy();
  }
  await page.goto('/');
  await page.getByRole('button',{name:/Ask Me/i}).click();
  const clear=page.waitForResponse(r=>/\/api\/v1\/cart\/clear(?:\?|$)/.test(r.url()));
  await page.getByPlaceholder('Type your message...').fill('Clear cart.');
  await page.getByPlaceholder('Type your message...').press('Enter');
  const cleared=await clear;
  expect(cleared.ok()).toBeTruthy();
  expect((await cleared.json()).undo).toEqual({available:true,count:2});
  await expect(page.getByText(/Undo available.*2 prior line item/i)).toBeVisible();
  const undo=page.waitForResponse(r=>/\/api\/v1\/cart\/undo(?:\?|$)/.test(r.url()));
  await page.getByRole('button',{name:/Restore/i}).click();
  const restored=await undo;
  expect(restored.ok()).toBeTruthy();
  expect((await restored.json()).items.map((p:{sku:string,quantity:number})=>({sku:p.sku,quantity:p.quantity}))).toEqual(lines);
  for(const line of lines)await expect(page.getByTestId(`qty-${line.sku}`)).toHaveText(String(line.quantity));
  const consumed=await page.request.post(`/api/v1/cart/undo?uid=${encodeURIComponent(buyerUid)}`);
  expect(consumed.status()).toBe(404);
});
