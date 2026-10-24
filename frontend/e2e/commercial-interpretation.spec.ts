import {test,expect} from './helpers/authenticatedTest';
import {turn} from './helpers/chatTurn';

for(const query of ['Dell 15 laptop under AUD 1400','15 inch laptops for work under AUD 1400']){
  test(`product description does not become bulk demand: ${query}`,async({page},info)=>{
    test.setTimeout(120000);
    await page.goto('/');
    await page.getByRole('button',{name:/Ask Me/i}).click({force:true});
    const result=await turn(page,query);
    await info.attach('answer.json',{body:JSON.stringify(result,null,2),contentType:'application/json'});
    expect([null,undefined,0,1]).toContain(result.requested_quantity);
    expect([null,undefined,0,1]).toContain(result.retained_buyer_facts?.requested_quantity);
    expect(result.next_questions?.some((q:any)=>q.goal==='resolve_budget_scope')??false).toBe(false);
    expect(result.terminal_outcome.commerce_authority).toBe('none');
    await expect(page.getByText(result.assistant_message,{exact:true}).last()).toBeVisible();
  });
}

test('budget maximum stays a commercial constraint through normal chat',async({page},info)=>{
  test.setTimeout(120000);
  await page.goto('/');
  await page.getByRole('button',{name:/Ask Me/i}).click({force:true});
  const result=await turn(page,'cut it to AUD 1300 max, work laptops');
  await info.attach('answer.json',{body:JSON.stringify(result,null,2),contentType:'application/json'});
  expect(result.retained_buyer_facts.budget.amount_minor).toBe(130000);
  const concepts=result.semantic_resolution?.concepts??[];
  expect(concepts.some((c:any)=>String(c.query_span??c.text).toLowerCase()==='max')).toBe(false);
  expect(result.terminal_outcome.commerce_authority).toBe('none');
  await expect(page.getByText(result.assistant_message,{exact:true}).last()).toBeVisible();
});
