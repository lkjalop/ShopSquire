import {test, expect} from './helpers/ordinaryBuyerTest';
import {terminalTurn as turn} from './helpers/terminalTurn';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';

// Imported August catalogue, illustrative stock, no workload/compatibility authority.
for (const scenario of [
  {category:'monitor', query:'Show me monitors under AUD 1000 each. I am browsing the catalogue.', names:/monitor|ultrasharp|proart|odyssey/i},
  {category:'bag', query:'Show me laptop bags under AUD 500 each. I am browsing the catalogue.', names:/bag|backpack|briefcase|sleeve/i},
  {category:'storage', query:'Show me external hard drives under AUD 1000 each. I am browsing the catalogue.', names:/drive|storage|ssd|seagate|western digital/i},
]) {
  test(`ordinary buyer can browse useful ${scenario.category} candidates from the mock file`, async ({page}, info) => {
    test.setTimeout(120000);
    const chatRequests:any[]=[];
    page.on('request',request=>{
      if(request.method()==='POST'&&/^\/api\/v1\/chat\/(query|stream)$/.test(new URL(request.url()).pathname))
        chatRequests.push(request.postDataJSON());
    });
    await page.goto('/'); await page.getByRole('button',{name:/Ask Me/i}).click();
    const answer=await turn(page,scenario.query);
    expect(chatRequests.length).toBeGreaterThan(0);
    for(const request of chatRequests)expect(request).not.toHaveProperty('storefront_taxonomy_handle');
    await info.attach('catalogue-answer.json',{body:JSON.stringify(answer,null,2),contentType:'application/json'});
    expect(answer.products?.length, 'Browsing must return useful in-category candidates').toBeGreaterThan(0);
    expect(answer.products.some((p:any)=>scenario.names.test(String(p.name ?? p.title ?? '')))).toBe(true);
    const source=readFileSync(join(process.env.ROADMAP_TEST_ROOT!,'docs/2026-08-08 laptop-products-aug.txt'),'utf8');
    // The importer joins wrapped product-title lines. Preserve the source
    // membership expectation across that documented whitespace normalization.
    const normalizedSource=source.replace(/\s+/g,' ').trim();
    for(const product of answer.products)expect(normalizedSource).toContain(String(product.name ?? product.title).replace(/\s+/g,' ').trim());
    expect(answer.terminal_outcome.commerce_authority).toBe('none');
    await expect(page.getByText(answer.assistant_message,{exact:true}).last()).toBeVisible();
    await expect(page.getByTestId('architecture-alternatives')).toHaveCount(0);
    await expect(page.getByRole('heading',{name:'Choose the requirements to evaluate'})).toHaveCount(0);
    await expect(page.getByText('Research unresolved',{exact:true})).toHaveCount(0);
    await expect(page.getByText('Windows Laptop Options',{exact:true})).toHaveCount(0);
    await expect(page.getByText('Catalogue options',{exact:true})).toBeVisible();
  });
}

test('buyer can request a laptop monitor and bag bundle without involuntary cart additions',async({page},info)=>{
  test.setTimeout(120000);
  const effects:string[]=[];
  page.on('request',r=>{
    if(r.method()==='POST' && /\/api\/v1\/(cart|orders|payments)(?:\/|$)/.test(new URL(r.url()).pathname))effects.push(r.url());
  });
  await page.goto('/'); await page.getByRole('button',{name:/Ask Me/i}).click();
  const answer=await turn(page,'Suggest a bundle with one laptop, one monitor and one laptop bag. AUD 3000 total for the complete bundle. Show choices only; do not add anything to my cart.');
  await info.attach('bundle-answer.json',{body:JSON.stringify(answer,null,2),contentType:'application/json'});
  const products=answer.products || [];
  for(const pattern of [/laptop|notebook|macbook/i,/monitor|ultrasharp|proart|odyssey/i,/bag|backpack|brief(?:case)?|sleeve|folio/i]) {
    expect.soft(products.some((p:any)=>pattern.test(String(p.name ?? p.title ?? ''))),`Bundle needs a candidate for ${pattern}`).toBe(true);
  }
  const bundle=answer.catalog_bundle;
  expect(bundle.status).toBe('within_listed_budget');
  expect(bundle.currency).toBe('AUD');
  expect(bundle.budget_cents).toBe(300000);
  expect(bundle.budget_scope).toBe('total');
  expect(bundle.lines.map((line:any)=>[line.taxonomy_handle,line.quantity])).toEqual([
    ['el-6-6',1],['el-17-1',1],['lb-15',1],
  ]);
  for(const line of bundle.lines){
    const product=products.find((item:any)=>item.sku===line.sku);
    expect(product).toBeDefined();
    expect(product.currency).toBe(bundle.currency);
    expect(product.price_cents).toBe(line.unit_price_cents);
  }
  expect(bundle.subtotal_cents).toBe(bundle.lines.reduce((total:number,line:any)=>total+line.quantity*line.unit_price_cents,0));
  expect(bundle.subtotal_cents).toBeLessThanOrEqual(bundle.budget_cents);
  expect(bundle.compatibility).toBe('not_assessed');
  expect(bundle.tax_and_freight).toBe('not_established');
  expect(answer.catalog_scope.requested_taxonomy_roots).toEqual(['el-6-6','el-17-1','lb-15']);
  expect(answer.catalog_scope.selected_taxonomy_root).toBeNull();
  expect(answer.terminal_outcome.commerce_authority).toBe('none');
  expect(effects).toEqual([]);
  await expect(page.getByText('Cart (0)',{exact:true})).toBeVisible();
  // Carousels may scroll internally; their parent panel must fit the dialog.
  const panel=page.getByText('Catalogue options',{exact:true}).locator('xpath=ancestor::div[contains(@class,"rightPanel")][1]');
  const panelBounds=await panel.boundingBox();
  const dialogBounds=await panel.locator('xpath=ancestor::div[contains(@class,"chatContainer")][1]').boundingBox();
  expect(panelBounds).not.toBeNull();
  expect(dialogBounds).not.toBeNull();
  expect(panelBounds!.x+panelBounds!.width).toBeLessThanOrEqual(dialogBounds!.x+dialogBounds!.width+1);
  const listedBag=products.find((product:any)=>product.sku===bundle.lines[2].sku);
  if(listedBag.price_cents%100!==0){
    await expect(page.getByText(new RegExp(`AUD\\s+${(listedBag.price_cents/100).toFixed(2)}`)).first()).toBeVisible();
  }
  await info.attach('bundle-browser-screen',{body:await page.screenshot({fullPage:true}),contentType:'image/png'});
});
