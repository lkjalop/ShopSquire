import {test,expect} from './helpers/authenticatedTest';

test('accepted quantity changes replace holds and invalidate qualification',async({page})=>{
  await page.goto('/?surface=qualified-shop');
  await page.getByRole('button',{name:'Start fictional buyer case'}).click();
  await page.getByLabel('Requirement scope').selectOption('fictional-memory-lab-v1');
  await page.getByRole('button',{name:'Select requirements'}).click();
  await expect(page.getByTestId('qualification-status')).toHaveText('Qualified for fictional scope');
  const available=Number(await page.getByTestId('live-available').innerText());
  expect(available).toBeGreaterThan(0);
  const held=Math.min(30,available);
  await page.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
  await expect(page.getByTestId('accepted-stock')).toHaveText(`Requested 30 · Held ${held} · Shortfall ${30-held}`);
  await expect(page.getByTestId('qualification-status')).toHaveText('Not qualified');
  await expect(page.getByTestId('hold-expiry')).toContainText('Hold deadline:');
  await expect(page.getByTestId('contract-state')).toHaveText('stale_case_revision');
  await page.getByLabel('Requested units').fill('40');
  await page.getByRole('button',{name:'Accept simulated stock request',exact:true}).click();
  await expect(page.getByTestId('accepted-stock')).toHaveText(`Requested 40 · Held ${Math.min(40,available)} · Shortfall ${Math.max(0,40-available)}`);
  await page.reload();
  await expect(page.getByTestId('hold-expiry')).toContainText('Expired holds cannot be shipped');
  await expect(page.getByTestId('accepted-stock')).toContainText('Requested 40');
  await expect(page.getByTestId('live-available')).toHaveText(String(Math.max(0,available-40)));
  await expect(page.getByTestId('qualification-status')).toHaveText('Not qualified');
  await page.getByRole('button',{name:'Release simulated holds'}).click();
  await expect(page.getByTestId('live-available')).toHaveText(String(available));
  await expect(page.getByTestId('accepted-stock')).toHaveText('Requested 40 · Held 0 · Shortfall 40');
});
