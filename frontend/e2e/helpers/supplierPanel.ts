import type {Page} from '@playwright/test';

export async function supplierPanel(page:Page,key:string,tenant:string){
  await page.addInitScript(value=>{
    sessionStorage.setItem('auth_email','fixture@example.invalid');
    sessionStorage.setItem('role','owner');
    sessionStorage.setItem('ss_owner_key',value);
  },key);
  await page.goto('/');
  await page.getByRole('button',{name:'Dashboard',exact:true}).click();
  await page.getByRole('button',{name:'Supply Chain Health',exact:true}).click();
  await page.getByLabel('Supplier tenant').fill(tenant);
}
