import {test,expect} from './helpers/authenticatedTest';

test('buyer selects fictional scope, qualifies, reloads and invalidates evidence',async({page})=>{
  await page.goto('/?surface=qualified-shop');
  await page.getByRole('button',{name:'Start fictional buyer case'}).click();
  await expect(page.getByTestId('qualification-status')).toHaveText('Not qualified');
  await page.getByLabel('Requirement scope').selectOption('fictional-memory-lab-v1');
  await page.getByRole('button',{name:'Select requirements'}).click();
  await expect(page.getByTestId('qualification-status')).toHaveText('Qualified for fictional scope');
  await page.reload();
  await expect(page.getByTestId('qualification-status')).toHaveText('Qualified for fictional scope');
  await page.getByLabel('Replay expired evidence').check();
  await expect(page.getByTestId('qualification-status')).toHaveText('Not qualified');
  await page.getByLabel('Replay expired evidence').uncheck();
  await expect(page.getByTestId('qualification-status')).toHaveText('Qualified for fictional scope');
  await page.getByRole('button',{name:'Revoke selection'}).click();
  await expect(page.getByTestId('qualification-status')).toHaveText('Not qualified');
  await page.getByText('Qualification trace',{exact:true}).click();
  await expect(page.getByTestId('qualification-trace')).toContainText('revoked');
  await expect(page.getByTestId('qualification-trace')).toContainText('"commerce_authority": "none"');
});
