import type {BrowserContext} from '@playwright/test';

/** Credentials belong to the explicitly enrolled, disposable test actor. */
export function fixtureMerchantHeaders():Record<string,string>{
  const key=process.env.MERCHANT_API_KEY?.trim();
  const tenant=process.env.VITE_STOREFRONT_TENANT_ID?.trim();
  if(!key||!tenant)throw new Error('Owned fixture merchant key and tenant are required');
  return {'x-api-key':key,'x-tenant-id':tenant};
}

export async function authenticateFixtureMerchant(context:BrowserContext,baseURL:string){
  const origin=new URL(baseURL).origin;
  const headers=fixtureMerchantHeaders();
  await context.route('**/api/v1/**',route=>{
    const request=route.request();
    return route.continue(new URL(request.url()).origin===origin
      ?{headers:{...request.headers(),...headers}}:{});
  });
}
