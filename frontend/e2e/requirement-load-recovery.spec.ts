import {test,expect} from './helpers/authenticatedTest';

test('failed requirement read offers recovery without mutating selection', async({page})=>{
  await page.route('**/api/v1/shopping-cases/**/requirement-contract?**',async route=>{
    if(route.request().method()==='GET') await route.abort('failed');
    else await route.continue();
  });
  await page.goto('/?surface=qualified-shop');
  await page.getByRole('button',{name:'Start fictional buyer case'}).click();
  await expect(page.getByRole('alert')).toContainText('Failed to fetch');
  await expect(page.getByLabel('Requirement scope')).toHaveCount(0);
  await page.unroute('**/api/v1/shopping-cases/**/requirement-contract?**');
  await page.getByRole('button',{name:'Retry loading requirements'}).click();
  await expect(page.getByTestId('contract-state')).toHaveText('unselected');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.getByLabel('Requirement scope').selectOption('fictional-memory-lab-v1');
  await page.getByRole('button',{name:'Select requirements'}).click();
  await expect(page.getByTestId('qualification-status')).toHaveText('Qualified for fictional scope');
});
