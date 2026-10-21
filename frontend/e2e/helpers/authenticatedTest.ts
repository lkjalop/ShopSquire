import {test as base, expect, type BrowserContext} from '@playwright/test';
import {createHmac} from 'node:crypto';

export const buyerUid='roadmap-browser-buyer';

// Only the test process holds this key. The application still verifies a real
// signed credential; no test endpoint or browser-side authority bypass exists.
export async function authenticateBuyer(context:BrowserContext,baseURL:string,subject=buyerUid){
    const secret=process.env.ROADMAP_TEST_JWT_KEY;
    if(!secret)throw new Error('ROADMAP_TEST_JWT_KEY must match the isolated server signing key');
    const now=Math.floor(Date.now()/1000);
    const encode=(value:unknown)=>Buffer.from(JSON.stringify(value)).toString('base64url');
    const unsigned=encode({alg:'HS256',typ:'JWT'})+'.'+encode({sub:subject,typ:'access',
      iss:'shopsquire',aud:'shopsquire-api',iat:now,exp:now+3600});
    const token=unsigned+'.'+createHmac('sha256',secret).update(unsigned).digest('base64url');
    await context.addCookies([{name:'shopsquire_access',value:token,url:baseURL!,httpOnly:true,sameSite:'Lax'}]);
    const tenant = process.env.VITE_STOREFRONT_TENANT_ID;
    await context.setExtraHTTPHeaders({'x-api-key':process.env.MERCHANT_API_KEY!,
      ...(tenant ? {'x-tenant-id':tenant} : {})});
    await context.addInitScript(uid=>sessionStorage.setItem('uid',uid),subject);
}
export const test=base.extend<{buyerSession:void;browserDiagnostics:void}>({
  buyerSession:[async({context,baseURL},use)=>{
    await authenticateBuyer(context,baseURL!);
    await use();
  },{auto:true}],
  browserDiagnostics:[async({page},use,info)=>{
    const failedRequests:unknown[]=[],scriptErrors:string[]=[];
    page.on('requestfailed',request=>failedRequests.push({path:new URL(request.url()).pathname,
      method:request.method(),error:request.failure()?.errorText}));
    page.on('pageerror',error=>scriptErrors.push(error.message));
    try{await use();}finally{
      await info.attach('browser-diagnostics.json',{body:JSON.stringify({failedRequests,scriptErrors}),contentType:'application/json'});
      expect(scriptErrors,'uncaught browser exceptions').toEqual([]);
    }
  },{auto:true}],
});
export {expect};
