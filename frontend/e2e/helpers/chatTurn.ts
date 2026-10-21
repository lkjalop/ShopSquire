import {expect,type Page,type Response} from '@playwright/test';
export async function turn(page:Page,query:string){
  const response=page.waitForResponse(r=>r.request().method()==='POST'&&/\/api\/v1\/chat\/(stream|query)(?:\?|$)/.test(r.url()),{timeout:65000});
  await page.getByPlaceholder('Type your message...').fill(query);
  await page.getByPlaceholder('Type your message...').press('Enter');
  const r=await response;
  return readChatResponse(r);
}
export async function readChatResponse(r:Response){
  expect(r.ok(),`chat HTTP ${r.status()}`).toBeTruthy();
  const body=await r.text();
  if(body.trim().startsWith('{'))return JSON.parse(body);
  const frames=body.replaceAll('\r\n','\n').split('\n\n').filter(f=>f.includes('event: answer'));
  const rows=frames.map(f=>JSON.parse(f.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trim()).join('\n')));
  const answer=rows.findLast(r=>r.status!=='in_progress');
  expect(answer,'completed chat answer').toBeTruthy();
  return answer;
}
