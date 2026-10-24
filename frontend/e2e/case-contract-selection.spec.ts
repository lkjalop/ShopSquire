import { test, expect, buyerUid } from './helpers/authenticatedTest';

test('case requirements persist across reload and reject a stale second tab', async ({ page, context }) => {
  const request=context.request;
  const uid = buyerUid;
  const created = await request.post('/api/v1/shopping-cases/browser-'+Date.now()+'/requirement-proposals/from-text', {
    data:{uid,text:'RAM 32GB minimum'},
  });
  expect(created.ok()).toBeTruthy();
  const caseId = (await created.json()).case_id;
  await context.addInitScript(value=>sessionStorage.setItem('uid',value), uid);
  const target = `/?surface=case-requirements&case_id=${encodeURIComponent(caseId)}`;
  await page.goto(target);
  await expect(page.getByTestId('contract-state')).toHaveText('unselected');
  const other = await context.newPage();
  await other.goto(target);
  await expect(other.getByTestId('contract-state')).toHaveText('unselected');
  for (const tab of [page,other]) await tab.getByLabel('Requirement scope').selectOption({index:1});
  await page.getByRole('button',{name:'Select requirements'}).click();
  await expect(page.getByTestId('contract-state')).toHaveText('current');
  await other.getByRole('button',{name:'Select requirements'}).click();
  await expect(other.getByRole('alert')).toContainText('changed');
  await page.reload();
  await expect(page.getByTestId('contract-state')).toHaveText('current');
  await page.getByRole('button',{name:'Revoke selection'}).click();
  await expect(page.getByTestId('contract-state')).toHaveText('revoked');
  await page.reload();
  await expect(page.getByTestId('contract-state')).toHaveText('revoked');
});
