import {expect, test, type Page, type Response} from '@playwright/test';
import { registerBuyer } from './helpers/registeredBuyer';
import path from 'node:path';
import {turnViolations} from './helpers/turnOracle';

async function turn(page: Page, query: string) {
  let handler: (response: Response) => Promise<void>;
  let timer: ReturnType<typeof setTimeout>;
  const result = new Promise<any>((resolve, reject) => {
    timer = setTimeout(() => reject(new Error('terminal response deadline')), 120_000);
    handler = async response => {
      if (!/\/chat\/(query|stream)|\/operations\//.test(response.url())) return;
      try {
        const raw = await response.text();
        const rows = raw.startsWith('{') ? [JSON.parse(raw)] : raw.replaceAll('\r\n', '\n')
          .split('\n\n').filter(row => row.includes('event: answer'))
          .map(row => JSON.parse(row.split('\n').find(line => line.startsWith('data: '))!.slice(6)));
        for (const row of rows) if (row.terminal_outcome) resolve(row);
      } catch { /* progress frames are not terminal evidence */ }
    };
    page.on('response', handler);
  });
  try {
    await page.getByPlaceholder('Type your message...').fill(query);
    await page.getByRole('button', {name:'Send message',exact:true}).click({timeout:120_000});
    return await result;
  } finally { clearTimeout(timer!); page.off('response', handler!); }
}

test('repeated live browser turns keep rendered answer and trace on the same revision', async ({page}, info) => {
  test.setTimeout(900_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await registerBuyer(page.context());
  await page.goto('/');
  await page.getByRole('button', {name:/Ask Me/i}).click({force:true});
  const queries = ['I need a laptop for university under AUD 1500.',
    'I need a laptop for Blender rendering and large scenes.',
    'Yes, research the official Blender requirements online.'];
  for (let cycle = 0; cycle < Number(process.env.ROADMAP_BROWSER_CYCLES || 3); cycle++) {
    for (const query of queries) {
      const started = Date.now();
      const body = await turn(page, query);
      await info.attach(`turn-${cycle}-${started}`, {body:JSON.stringify({query,elapsed_ms:Date.now()-started,body}), contentType:'application/json'});
      expect(turnViolations(body, {buyerQuery:query})).toEqual([]);
      const terminal = body.terminal_outcome;
      expect(terminal.commerce_authority).toBe('none');
      if (terminal.catalog_authority !== 'permitted') {
        await expect(page.getByRole('button', {name:/for the real fit/i})).toHaveCount(0);
      }
      await expect(page.getByText(terminal.assistant_message, {exact:true}).last()).toBeVisible();
      await page.getByTitle('Decision Trace', {exact:true}).click();
      const trace = page.getByTestId('decision-trace-modal');
      await expect(trace.getByTestId('revision-bound-turn-projection')).toContainText(`Case revision ${terminal.case_revision}`);
      await expect(trace.getByTestId('revision-bound-research-outcome')).toContainText(`${terminal.research_outcome.accepted_claim_count} accepted`);
      await trace.getByTitle('Close', {exact:true}).click();
    }
  }
  expect(errors).toEqual([]);
});

test('buyer request researches official Blender requirements in a fresh case', async ({page}, info) => {
  test.setTimeout(180_000);
  await registerBuyer(page.context());
  await page.goto('/');
  await page.getByRole('button', {name:/Ask Me/i}).click({force:true});
  const body = await turn(page, 'I need a laptop for Blender rendering and large scenes. Please research the official requirements.');
  await info.attach('research-entry', {body:JSON.stringify(body),contentType:'application/json'});
  expect(turnViolations(body)).toEqual([]);
  const terminal = body.terminal_outcome;
  expect(terminal.research_outcome.accepted_claim_count).toBeGreaterThan(0);
  expect(terminal.commerce_authority).toBe('none');
  await expect(page.getByText(terminal.assistant_message, {exact:true}).last()).toBeVisible();
  await expect(page.getByText(/Accepted: 1/).last()).toBeVisible();
  await page.getByTitle('Decision Trace', {exact:true}).click();
  const trace = page.getByTestId('decision-trace-modal');
  await expect(trace.getByTestId('revision-bound-turn-projection')).toContainText(`Case revision ${terminal.case_revision}`);
  await expect(trace.getByTestId('revision-bound-research-outcome')).toContainText('1 accepted');
  await trace.getByTitle('Close', {exact:true}).click();
});

test('changed workload binds research to the new case without inherited consent', async ({page}, info) => {
  test.setTimeout(240_000);
  await registerBuyer(page.context());
  await page.goto('/');
  await page.getByRole('button', {name:/Ask Me/i}).click({force:true});
  const first = await turn(page, 'I need a laptop for university under AUD 1500.');
  const changed = await turn(page, 'I need a laptop for Blender rendering and large scenes.');
  await info.attach('changed-workload', {body:JSON.stringify(changed),contentType:'application/json'});
  expect(changed.terminal_outcome.case_id).not.toBe(first.terminal_outcome.case_id);
  expect(changed.terminal_outcome.research_outcome.accepted_claim_count).toBe(0);
  const researched = await turn(page, 'Please research the official Blender requirements online.');
  await info.attach('continued-research', {body:JSON.stringify(researched),contentType:'application/json'});
  expect(researched.terminal_outcome.case_id).toBe(changed.terminal_outcome.case_id);
  expect(researched.terminal_outcome.research_outcome.accepted_claim_count).toBeGreaterThan(0);
  expect(turnViolations(researched)).toEqual([]);
  expect(researched.terminal_outcome.commerce_authority).toBe('none');
});

test('repeated browser image uploads reach bounded triage before further text turns', async ({page}, info) => {
  test.setTimeout(600_000);
  await registerBuyer(page.context());
  await page.goto('/');
  await page.getByRole('button', {name:/Ask Me/i}).click({force:true});
  for (let cycle=0; cycle<3; cycle++) {
    await page.locator("input[type='file']").last().setInputFiles(path.resolve('../tests/fixtures/browser_images/macbook.jpg'));
    await expect(page.getByRole('img', {name:'attached 1'})).toBeVisible();
    const response = page.waitForResponse(r => r.url().includes('/vision/triage')
      && !new URL(r.url()).searchParams.has('fast') && r.request().method()==='POST', {timeout:120_000});
    await page.getByPlaceholder('Type your message...').fill('Identify the laptop in this image. Do not add anything to my cart.');
    await page.getByRole('button', {name:'Send message',exact:true}).click();
    const triage = await response;
    const payload = await triage.json();
    await info.attach(`image-${cycle}`, {body:JSON.stringify({status:triage.status(),payload}),contentType:'application/json'});
    expect(triage.status()).toBe(200);
    expect(payload).toHaveProperty('artifact');
    expect((payload.analysis_state?.degraded_reasons || []).filter((r: string) => /vision_provider|model_execution|model_artifact|local_model/.test(r))).toEqual([]);
    expect((payload.labels || []).join(' ').toLowerCase()).toMatch(/apple|macbook/);
    await expect(page.getByPlaceholder('Type your message...')).toBeEnabled({timeout:120_000});
    const body = await turn(page, 'I need a laptop for university under AUD 1500.');
    await info.attach(`after-image-${cycle}`, {body:JSON.stringify(body),contentType:'application/json'});
    expect(turnViolations(body)).toEqual([]);
    expect(body.terminal_outcome.commerce_authority).toBe('none');
  }
});
