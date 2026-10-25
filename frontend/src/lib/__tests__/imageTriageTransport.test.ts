import {afterEach,expect,it,vi} from 'vitest';
import {fetchImageTriages} from '../imageTriageTransport';

afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
const file=()=>Object.assign(new File(['transport fixture'],'safe.png',{type:'image/png'}),{__shopsquireArtifactId:'client-image'});
const prior=[{_filename:'safe.png',artifact:{artifact_id:'server-owned',state:'pending',authority:'blocked'}}];
const response=(body:any,status=200)=>({ok:status>=200&&status<300,status,json:async()=>body}) as Response;

it('ends stalled deep inspection at 30 seconds with blocked degraded evidence',async()=>{
  vi.useFakeTimers();
  const request=vi.fn((_url:any,init:any)=>new Promise<Response>((_resolve,reject)=>{
    init.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});
  }));
  vi.stubGlobal('fetch',request);
  let result:any=null;
  void fetchImageTriages([file()],false,false,prior).then(value=>{result=value;});
  await vi.advanceTimersByTimeAsync(29999);expect(result).toBeNull();
  await vi.advanceTimersByTimeAsync(1);
  expect(request.mock.calls[0][1].signal.aborted).toBe(true);
  expect(result?.[0]?.artifact).toEqual({artifact_id:'server-owned',state:'degraded',authority:'blocked'});
  expect(result[0].security.commercial_authority).toBe('blocked');
  expect(result[0]._upload_error).toBe('triage_unavailable');
  expect(vi.getTimerCount()).toBe(0);
});
it('keeps the fast boundary pending after its three-second deadline',async()=>{
  vi.useFakeTimers();
  vi.stubGlobal('fetch',vi.fn((_url:any,init:any)=>new Promise<Response>((_resolve,reject)=>{
    init.signal.addEventListener('abort',()=>reject(new Error('deadline')),{once:true});
  })));
  const pending=fetchImageTriages([file()],true);
  await vi.advanceTimersByTimeAsync(3000);
  const [row]=await pending;
  expect(row.artifact).toEqual({artifact_id:'client-image',state:'pending',authority:'blocked'});
  expect(row.security.signals.fast_triage_timeout).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});
it('preserves server inspection authority and clears its deadline after success',async()=>{
  vi.useFakeTimers();
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({artifact:{artifact_id:'server-owned',state:'quarantined',authority:'blocked'}})));
  const [row]=await fetchImageTriages([file()],false);
  expect(row.artifact.state).toBe('quarantined');expect(row._filename).toBe('safe.png');
  expect(vi.getTimerCount()).toBe(0);
});
it('retains server rejection without retries or a privileged fallback',async()=>{
  const request=vi.fn().mockResolvedValue(response({detail:{error:'tenant_forbidden'}},403));vi.stubGlobal('fetch',request);
  const [row]=await fetchImageTriages([file()],false);
  expect(row._http_status).toBe(403);expect(row._upload_error).toBe('tenant_forbidden');
  expect(row.security.commercial_authority).toBe('blocked');expect(request).toHaveBeenCalledTimes(1);
});
it('retains the bound artifact identity when a deep response is empty',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response(null)));
  const [row]=await fetchImageTriages([file()],false,false,prior);
  expect(row.artifact).toEqual({artifact_id:'server-owned',state:'degraded',authority:'blocked'});
});
it('does not borrow an artifact identity from another filename on transport failure',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')));
  const [row]=await fetchImageTriages([file()],false,false,[{_filename:'another.png',artifact:{artifact_id:'foreign-artifact'}}]);
  expect(row.artifact).toEqual({artifact_id:'client-image',state:'degraded',authority:'blocked'});
});
