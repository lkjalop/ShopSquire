import type {Page,Request,Response} from '@playwright/test';

// Observe the same JSON/SSE/POST-poll paths as the storefront. Only requests
// started for this query, actor and session may complete this caller's turn.
export async function terminalTurn(page:Page,query:string,{timeoutMs=150_000}={}){
  if(!Number.isFinite(timeoutMs)||timeoutMs<=0||timeoutMs>150_000)
    throw new Error('terminal deadline must be within 150000ms');
  let resolveResult!:(value:any)=>void;
  let rejectResult!:(error:Error)=>void;
  const result=new Promise<any>((resolve,reject)=>{resolveResult=resolve;rejectResult=reject;});
  // A fill/press failure can happen before the caller starts awaiting result.
  // Keep its rejection observed while the finally block releases our resources.
  void result.catch(()=>undefined);
  let active=false,settled=false;
  let identity:string|undefined,operation:string|undefined;
  const requests=new WeakSet<Request>();
  const fail=(error:unknown)=>{
    if(settled)return;
    settled=true;
    rejectResult(error instanceof Error?error:new Error(String(error)));
  };
  const timer=setTimeout(()=>fail(new Error('terminal deadline')),timeoutMs);
  const onRequest=(request:Request)=>{
    if(!active||settled||request.method()!=='POST'
      ||!/^\/api\/v1\/chat\/(query|stream)$/.test(new URL(request.url()).pathname))return;
    let body:any;
    try{body=request.postDataJSON();}catch{return;}
    if(body?.query!==query)return;
    const key=JSON.stringify([body.uid??null,body.session_id??null]);
    if(identity===undefined)identity=key;
    if(key===identity)requests.add(request);
  };
  const accept=(row:any)=>{
    if(settled)return;
    if(!row||typeof row!=='object'||Array.isArray(row))throw new Error('invalid terminal response');
    const terminal=row.terminal_outcome;
    if(terminal&&row.operation_id&&terminal.operation_id!==row.operation_id)
      throw new Error('operation identity mismatch');
    const nextOperation=row.operation_id||terminal?.operation_id;
    if(typeof nextOperation!=='string'||!nextOperation)
      throw new Error('terminal operation identity missing');
    if(operation!==undefined&&nextOperation!==operation)return;
    operation=nextOperation;
    if(row.status==='in_progress')return;
    if(!terminal?.operation_id)throw new Error('terminal outcome missing');
    settled=true;resolveResult(row);
  };
  const inspect=async(response:Response)=>{
    if(settled||!requests.has(response.request()))return;
    if(!response.ok())throw new Error(`chat HTTP ${response.status()}`);
    const body=(await response.text()).trim();
    let rows:any[];
    try{
      if(response.headers()['content-type']?.includes('application/json')||body.startsWith('{')){
        rows=[JSON.parse(body)];
      }else{
        rows=body.replaceAll('\r\n','\n').split('\n\n')
          .filter(frame=>/^event:\s*answer\s*$/m.test(frame))
          .map(frame=>JSON.parse(frame.split('\n').filter(line=>line.startsWith('data:'))
            .map(line=>line.slice(5).trimStart()).join('\n')));
      }
    }catch{throw new Error('invalid terminal response');}
    for(const row of rows)accept(row);
  };
  const onResponse=(response:Response)=>{void inspect(response).catch(fail);};
  const onClose=()=>fail(new Error('page closed before terminal response'));
  page.on('request',onRequest);page.on('response',onResponse);page.on('close',onClose);
  try{
    await page.getByPlaceholder('Type your message...').fill(query);
    active=true;
    await page.getByPlaceholder('Type your message...').press('Enter');
    return await result;
  }catch(error){fail(error);throw error;}
  finally{
    active=false;clearTimeout(timer);
    page.off('request',onRequest);page.off('response',onResponse);page.off('close',onClose);
  }
}
