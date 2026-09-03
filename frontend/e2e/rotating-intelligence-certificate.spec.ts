import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

type RotationCase = {
  scenario: string;
  title: string;
  query_title: string;
  appid: number | null;
  release_state: string;
  requirements_completeness: string;
};

const manifestPath = process.env.ROTATING_INTELLIGENCE_MANIFEST
  ? path.resolve(process.env.ROTATING_INTELLIGENCE_MANIFEST)
  : '';
const manifest = manifestPath && fs.existsSync(manifestPath)
  ? JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  : null;

async function send(page: Page, query: string) {
  let finish!: (value: any) => void;
  let fail!: (reason: Error) => void;
  const terminal = new Promise<any>((resolve, reject) => { finish = resolve; fail = reject; });
  const timer = setTimeout(() => fail(new Error('terminal answer timeout')), 180_000);
  const onResponse = async (response: import('@playwright/test').Response) => {
    if (response.request().method() !== 'POST'
      || !/\/api\/v1\/chat\/(?:query|stream)(?:\?|$)/.test(response.url())) return;
    try {
      if (!response.ok()) throw new Error(`chat response ${response.status()}`);
      const body = await response.text();
      const payloads: any[] = [];
      if (!body.includes('data:')) payloads.push(JSON.parse(body));
      else for (const frame of body.replaceAll('\r\n', '\n').split('\n\n')) {
        if (!frame.includes('event: answer')) continue;
        const raw = frame.split('\n').filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).trim()).join('\n');
        if (raw) payloads.push(JSON.parse(raw));
      }
      const completed = payloads.find(item => item?.status !== 'in_progress');
      if (completed) finish(completed);
    } catch (error) {
      fail(error instanceof Error ? error : new Error(String(error)));
    }
  };
  page.on('response', onResponse);
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(query);
  await input.press('Enter');
  try {
    return await terminal;
  } finally {
    clearTimeout(timer);
    page.off('response', onResponse);
  }
}

test('seeded official-feed titles exercise generic identity and fail-closed behavior', async ({ page }, testInfo) => {
  test.skip(process.env.RUN_ROTATING_INTELLIGENCE_CERT !== '1', 'requires explicit live certificate opt-in');
  test.skip(!manifest, 'ROTATING_INTELLIGENCE_MANIFEST does not exist');
  test.setTimeout(900_000);
  await testInfo.attach('selection-manifest.json', {
    body: Buffer.from(JSON.stringify(manifest, null, 2)), contentType: 'application/json',
  });

  const uid = `rotating-intelligence-${manifest.seed}-${Date.now()}`;
  await page.addInitScript(value => {
    localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem('uid', value);
  }, uid);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click({ force: true });

  for (const [index, scenario] of (manifest.cases as RotationCase[]).entries()) {
    // A fresh-search phrase prevents the previous rotating title from becoming
    // accidental evidence while still exercising the ordinary buyer surface.
    const query = scenario.appid
      ? `New search: can a laptop under AUD 3,000 run ${scenario.query_title}? Identify its release state and official requirements.`
      : `New search: can a laptop run ${scenario.query_title}? Verify whether that product exists before recommending anything.`;
    const answer = await send(page, query);
    await testInfo.attach(`case-${index}-${scenario.scenario}.json`, {
      body: Buffer.from(JSON.stringify(answer, null, 2)), contentType: 'application/json',
    });

    expect(answer.terminal_outcome?.operation_id).toBe(answer.operation_id);
    expect(answer.terminal_outcome?.case_revision).toBe(answer.case_revision);
    expect(answer.terminal_outcome?.execution_evidence?.core_invocation_count).toBe(1);
    expect(answer.action_executed).not.toBe(true);
    if (scenario.appid) {
      const identity = answer.terminal_outcome?.research_outcome?.identity
        || answer.server_research_result?.research?.identity_resolution?.identity
        || {};
      if (scenario.scenario.includes('typo') && !identity.title && !identity.canonical_title) {
        // A typo in a just-published title may not yet exist in any official
        // search index. The invariant is still intelligence, not guessing:
        // research must run and the catalogue must remain withheld.
        expect(answer.terminal_outcome?.research_outcome?.discovery_status).toBe('completed');
        expect(answer.products || []).toHaveLength(0);
      } else {
        expect(String(identity.title || identity.canonical_title || '')).toBe(scenario.title);
        expect(Number(identity.app_id || identity.appid)).toBe(scenario.appid);
        expect(String(identity.release_state || '')).toBe(scenario.release_state);
      }
      expect(JSON.stringify(answer)).not.toMatch(/general (office|gaming)|which level fits/i);
    } else {
      expect(answer.products || []).toHaveLength(0);
      expect(JSON.stringify(answer)).toMatch(/unresolved|not resolved|could not verify|no authoritative/i);
    }
    await expect(page.getByText('Cart (0)', { exact: true })).toBeVisible();
  }

  await page.getByTitle('Decision Trace').click();
  const trace = page.getByTestId('decision-trace-modal');
  for (const tab of [
    'Decision', 'Research & Fit', 'Reasoning', 'Evidence & Risk',
    'Commercial Journey', 'Advanced technical details',
  ]) {
    await trace.getByRole('button', { name: new RegExp(`^${tab}`) }).click();
    await expect(trace).toBeVisible();
    await expect(trace).not.toContainText(/404|not found/i);
  }
});
