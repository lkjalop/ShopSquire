import {test as base, expect} from '@playwright/test';
import {registerBuyer} from './registeredBuyer';

/** Native account/cookies only; never borrow the fixture merchant's authority. */
export const test=base.extend<{ordinaryBuyer:void}>({
  ordinaryBuyer:[async({page,context},use)=>{
    await registerBuyer(context);
    const privileged:string[]=[], errors:string[]=[];
    page.on('request',r=>{
      if(new URL(r.url()).pathname.startsWith('/api/v1/') && r.headers()['x-api-key'])privileged.push(r.url());
    });
    page.on('pageerror',error=>errors.push(error.message));
    try { await use(); } finally {
      expect(privileged,'Ordinary buyers must not borrow operator credentials').toEqual([]);
      expect(errors,'Uncaught browser errors').toEqual([]);
    }
  },{auto:true}],
});
export {expect};
