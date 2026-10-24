import {test,expect} from './helpers/authenticatedTest';
import {turn} from './helpers/chatTurn';
import {readFileSync,writeFileSync} from 'node:fs';

test('accepted buyer facts survive a real server restart without Redis',async({page},info)=>{
  await page.context().setExtraHTTPHeaders({'x-tenant-id':process.env.VITE_STOREFRONT_TENANT_ID!});
  const file=process.env.ROADMAP_RESTART_STATE;
  const stage=process.env.ROADMAP_RESTART_STAGE;
  if(!file||!['before','after'].includes(stage||''))throw new Error('Run through the supervised restart harness');
  let prior:any;
  if(stage==='after'){
    prior=JSON.parse(readFileSync(file,'utf8'));
    await page.addInitScript((values:Record<string,string>)=>{
      for(const [key,value] of Object.entries(values))sessionStorage.setItem(key,value);
    },prior.session);
  }
  await page.goto('/');
  await page.getByRole('button',{name:/Ask Me/i}).click({force:true});
  if(stage==='before'){
    await turn(page,'I need 30 work laptops with AUD 1500 per laptop.');
    await turn(page,'Actually make that 40 units.');
    await turn(page,'Deliver to Parramatta.');
    await turn(page,'Deliver by 2030-10-12T17:00:00+11:00.');
    const result=await turn(page,'Summarise my quantity, budget and destination.');
    expect(result.retained_buyer_facts.requested_quantity).toBe(40);
    expect(result.retained_buyer_facts.temporal.original_expression).toContain('2030-10-12');
    const session=await page.evaluate(()=>Object.fromEntries(Object.keys(sessionStorage).map(k=>[k,sessionStorage.getItem(k)!])));
    writeFileSync(file,JSON.stringify({session,case_id:result.case_id,facts:result.retained_buyer_facts}));
  }else{
    const result=await turn(page,'Remind me how many laptops I requested and where to deliver them.');
    expect(result.case_id).toBe(prior.case_id);
    expect(result.retained_buyer_facts).toEqual(prior.facts);
    expect(result.terminal_outcome.commerce_authority).toBe('none');
    await expect(page.getByText(result.assistant_message,{exact:true}).last()).toBeVisible();
    await info.attach('restart-restored.json',{body:JSON.stringify(result),contentType:'application/json'});
  }
});
