import {test,expect,type Page} from '@playwright/test';
import {terminalTurn} from './helpers/terminalTurn';

const query='Retain the current forty-unit request';
const completed=(operation='owned-operation')=>({operation_id:operation,
  terminal_outcome:{operation_id:operation,case_revision:'revision-7'}});
type Step={body:unknown;status?:number;contentType?:string;query?:string;uid?:string};

function responseListeners(page:Page):number{
  // This read-only runtime diagnostic is omitted from Playwright's public
  // Page interface; validate its presence instead of weakening the type check.
  const inspect=Reflect.get(page,'listenerCount');
  if(typeof inspect!=='function')throw new Error('Page listener inspection unavailable');
  const count=Reflect.apply(inspect,page,['response']);
  if(typeof count!=='number'||!Number.isInteger(count))throw new Error('Invalid Page listener count');
  return count;
}

async function mockConversation(page:Page,steps:Step[]){
  let index=0;
  await page.route('https://terminal-turn.invalid/**',async route=>{
    if(new URL(route.request().url()).pathname==='/'){
      const requests=steps.map(step=>({query:step.query,uid:step.uid}));
      await route.fulfill({contentType:'text/html',body:`<!doctype html><textarea placeholder="Type your message..."></textarea>
        <script>const requests=${JSON.stringify(requests)};
        document.querySelector('textarea').addEventListener('keydown',async event=>{
          if(event.key!=='Enter')return;
          event.preventDefault();
          const query=event.target.value;
          for(const request of requests){
            await fetch('/api/v1/chat/query',{method:'POST',headers:{'Content-Type':'application/json'},
              body:JSON.stringify({query:request.query||query,uid:request.uid||'owned-buyer',session_id:'owned-epoch'})}).then(response=>response.text());
          }
        });</script>`});
      return;
    }
    const step=steps[index++];
    if(!step){await route.fulfill({status:500,body:'Unexpected extra request'});return;}
    await route.fulfill({status:step.status||200,contentType:step.contentType||'application/json',
      body:typeof step.body==='string'?step.body:JSON.stringify(step.body)});
  });
  await page.goto('https://terminal-turn.invalid/');
}

test('terminal helper accepts a completed JSON turn and releases its listener',async({page})=>{
  await mockConversation(page,[{body:completed()}]);
  const listeners=responseListeners(page);
  expect(await terminalTurn(page,query,{timeoutMs:500})).toEqual(completed());
  expect(responseListeners(page)).toBe(listeners);
});

for(const status of [401,403])test(`terminal helper exposes HTTP ${status} instead of waiting for a successful answer`,async({page})=>{
  await mockConversation(page,[{status,body:{detail:'actor_not_authorized'}}]);
  const listeners=responseListeners(page);
  await expect(terminalTurn(page,query,{timeoutMs:500})).rejects.toThrow(`chat HTTP ${status}`);
  expect(responseListeners(page)).toBe(listeners);
});

test('terminal helper preserves multiline CRLF SSE data',async({page})=>{
  const body='event: answer\r\ndata: {"operation_id":"owned-operation",\r\ndata: "terminal_outcome":{"operation_id":"owned-operation","case_revision":"revision-7"}}\r\n\r\n';
  await mockConversation(page,[{contentType:'text/event-stream',body}]);
  expect(await terminalTurn(page,query,{timeoutMs:500})).toEqual(completed());
});

test('terminal helper keeps the pending operation through its actual POST poll',async({page})=>{
  await mockConversation(page,[{body:{status:'in_progress',operation_id:'owned-operation'}},{body:completed()}]);
  expect(await terminalTurn(page,query,{timeoutMs:500})).toEqual(completed());
});

test('terminal helper ignores another query response',async({page})=>{
  await mockConversation(page,[{body:completed('foreign-query'),query:'A different request'},{body:completed()}]);
  expect(await terminalTurn(page,query,{timeoutMs:500})).toEqual(completed());
});

test('terminal helper ignores another actor response',async({page})=>{
  await mockConversation(page,[{body:{status:'in_progress',operation_id:'owned-operation'}},
    {body:completed('foreign-actor'),uid:'other-buyer'},{body:completed()}]);
  expect(await terminalTurn(page,query,{timeoutMs:500})).toEqual(completed());
});

test('terminal helper cannot replace its pending operation with a foreign completed operation',async({page})=>{
  await mockConversation(page,[{body:{status:'in_progress',operation_id:'owned-operation'}},
    {body:completed('foreign-operation')},{body:completed()}]);
  expect(await terminalTurn(page,query,{timeoutMs:500})).toEqual(completed());
});

test('terminal helper rejects inconsistent envelope and terminal operation identities',async({page})=>{
  await mockConversation(page,[{body:{...completed(),operation_id:'different-envelope'}}]);
  await expect(terminalTurn(page,query,{timeoutMs:500})).rejects.toThrow('operation identity mismatch');
});

test('terminal helper exposes malformed JSON instead of hiding the parser failure',async({page})=>{
  await mockConversation(page,[{body:'{"status":',contentType:'application/json'}]);
  await expect(terminalTurn(page,query,{timeoutMs:500})).rejects.toThrow('invalid terminal response');
});

test('terminal helper retains its deadline when no completed turn arrives',async({page})=>{
  await mockConversation(page,[{body:{status:'in_progress',operation_id:'owned-operation'}}]);
  const listeners=responseListeners(page);
  await expect(terminalTurn(page,query,{timeoutMs:100})).rejects.toThrow('terminal deadline');
  expect(responseListeners(page)).toBe(listeners);
});
