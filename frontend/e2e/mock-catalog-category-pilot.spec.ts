import {test, expect} from './helpers/authenticatedTest';
import {turn} from './helpers/chatTurn';

// Imported August catalogue, illustrative stock, no workload/compatibility authority.
for (const scenario of [
  {category:'monitor', query:'Show me monitors under AUD 1000 each. I am browsing the catalogue.', names:/monitor|ultrasharp|proart|odyssey/i},
  {category:'bag', query:'Show me laptop bags under AUD 500 each. I am browsing the catalogue.', names:/bag|backpack|briefcase|sleeve/i},
  {category:'storage', query:'Show me external hard drives under AUD 1000 each. I am browsing the catalogue.', names:/drive|storage|ssd|seagate|western digital/i},
]) {
  test(`ordinary buyer can browse useful ${scenario.category} candidates from the mock file`, async ({page}, info) => {
    test.setTimeout(120000);
    await page.goto('/'); await page.getByRole('button',{name:/Ask Me/i}).click();
    const answer=await turn(page,scenario.query);
    await info.attach('catalogue-answer.json',{body:JSON.stringify(answer,null,2),contentType:'application/json'});
    expect(answer.products?.length, 'Browsing must return useful in-category candidates').toBeGreaterThan(0);
    expect(answer.products.some((p:any)=>scenario.names.test(String(p.name ?? p.title ?? '')))).toBe(true);
    expect(answer.terminal_outcome.commerce_authority).toBe('none');
    await expect(page.getByText(answer.assistant_message,{exact:true}).last()).toBeVisible();
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
  for(const pattern of [/laptop|notebook|macbook/i,/monitor|ultrasharp|proart|odyssey/i,/bag|backpack|briefcase|sleeve/i]) {
    expect.soft(products.some((p:any)=>pattern.test(String(p.name ?? p.title ?? ''))),`Bundle needs a candidate for ${pattern}`).toBe(true);
  }
  expect(answer.terminal_outcome.commerce_authority).toBe('none');
  expect(effects).toEqual([]);
  await expect(page.getByText('Cart (0)',{exact:true})).toBeVisible();
});
