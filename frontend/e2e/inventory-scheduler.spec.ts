import {test,expect,buyerUid} from './helpers/authenticatedTest';
import {execFileSync} from 'child_process';

test('scheduled expiry releases an accepted buyer hold and records one durable expiry',async({page},info)=>{
  test.setTimeout(100000);
  const python=process.env.ROADMAP_TEST_PYTHON!;
  const env=process.env;
  const options={env,encoding:'utf8' as const,cwd:process.env.ROADMAP_TEST_ROOT,timeout:15000};
  const fixture=JSON.parse(execFileSync(python,['-m','scripts.create_short_hold_probe','--uid',buyerUid],options).trim());
  await page.addInitScript(uid=>sessionStorage.setItem('uid',uid),fixture.uid);
  await page.goto(`/?surface=qualified-shop&case_id=${encodeURIComponent(fixture.case_id)}`);
  await expect(page.getByTestId('accepted-stock')).toContainText('Held 1');
  await expect(page.getByTestId('live-available')).toHaveText(String(fixture.initial_available-1));
  await expect.poll(async()=>{
    await page.getByRole('button',{name:'Refresh stock',exact:true}).click();
    return Number(await page.getByTestId('live-available').innerText());
  },{timeout:70000,intervals:[2000]}).toBe(fixture.initial_available);
  await expect(page.getByTestId('accepted-stock')).toContainText('Held 0');
  const code=`import json,os,sqlite3,sys
from sqlalchemy.engine import make_url
c=sqlite3.connect(make_url(os.environ['DATABASE_URL']).database)
rows=c.execute("SELECT r.status,e.kind,COUNT(*) FROM inventory_reservation r JOIN inventory_effect_event e ON r.tenant_id=e.tenant_id AND r.reservation_id=e.reservation_id WHERE r.tenant_id='synthetic-electronics' AND r.reservation_id LIKE ? GROUP BY r.status,e.kind",('selection:'+sys.argv[1]+':%',)).fetchall()
print(json.dumps(rows))`;
  const events=JSON.parse(execFileSync(python,['-c',code,fixture.accepted.selection_id],options));
  expect(events).toEqual([['expired','expire',1],['expired','reserve',1]]);
  await info.attach('scheduled-expiry.json',{body:JSON.stringify({fixture,events},null,2),contentType:'application/json'});
});
