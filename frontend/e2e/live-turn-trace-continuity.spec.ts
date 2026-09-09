import { expect, test, type Page, type Response } from '@playwright/test';

const sections = {
  'Decision': ['summary', 'events', 'execution'],
  'Research & Fit': ['research', 'why'],
  'Reasoning': ['intent', 'memory', 'complexity'],
  'Evidence & Risk': ['evidence', 'multimodal', 'security'],
  'Commercial Journey': ['market', 'procurement'],
  'Advanced technical details': ['audit', 'raw'],
};

async function send(page: Page, query: string): Promise<any> {
  let handler: (response: Response) => Promise<void>;
  let timer: ReturnType<typeof setTimeout>;
  const answer = new Promise<any>((resolve, reject) => {
    timer = setTimeout(() => reject(new Error('No terminal turn outcome')), 180_000);
    handler = async response => {
      if (!/\/chat\/(query|stream)|\/operations\//.test(response.url())) return;
      try {
        const text = await response.text();
        const rows = text.startsWith('{') ? [JSON.parse(text)] : text.replaceAll('\r\n', '\n')
          .split('\n\n').filter(row => row.includes('event: answer'))
          .map(row => JSON.parse(row.split('\n').find(line => line.startsWith('data: '))!.slice(6)));
        for (const row of rows) if (row.terminal_outcome) resolve(row);
      } catch { /* Non-terminal progress frames carry no recommendation authority. */ }
    };
    page.on('response', handler);
  });
  try {
    await page.getByPlaceholder('Type your message...').fill(query);
    await page.getByPlaceholder('Type your message...').press('Enter');
    return await answer;
  } finally { clearTimeout(timer!); page.off('response', handler!); }
}

test('live category and quantity turns retain their own trace and recorded history', async ({ page }, info) => {
  test.setTimeout(540_000);
  const dispatches: string[] = [];
  const failures: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /confirm-cart|send-approved|send-autonomous/.test(request.url())) dispatches.push(request.url());
  });
  page.on('response', response => {
    if (response.url().includes('/api/') && response.status() >= 400) failures.push(`${response.status()} ${response.url()}`);
  });
  await page.addInitScript(uid => {
    localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem('uid', uid);
  }, `trace-continuity-${Date.now()}`);
  await page.goto('/');
  await page.getByRole('button', {name:/Ask Me/i}).click({force:true});
  const operations = new Set<string>();
  const traces = new Set<string>();
  let previousTerminal: any;
  for (const query of [
    'Could a laptop under AUD 2,500 run PRAGMATA at 1080p?',
    'Actually I need a computer chair under AUD 400, not a laptop.',
    'Now I need 10 laptops with a total budget of AUD 30,000.',
    'Make that 12 laptops, keeping the total budget at AUD 30,000.',
  ]) {
    const data = await send(page, query);
    const terminal = data.terminal_outcome;
    expect(terminal.operation_id).toBeTruthy();
    expect(operations.has(terminal.operation_id)).toBe(false);
    operations.add(terminal.operation_id);
    expect(terminal.decision_trace_id).toBeTruthy();
    expect(traces.has(terminal.decision_trace_id)).toBe(false);
    traces.add(terminal.decision_trace_id);
    expect(data.turn_read_model.operation_id).toBe(terminal.operation_id);
    expect(data.turn_read_model.case_revision).toBe(terminal.case_revision);
    expect(terminal.commerce_authority).toBe('none');
    if (operations.size === 4) {
      expect(terminal.case_id).toBe(previousTerminal.case_id);
      expect(terminal.case_revision).toBe(previousTerminal.case_revision + 1);
    }
    await page.getByTitle('Decision Trace', {exact:true}).click();
    const modal = page.getByTestId('decision-trace-modal');
    await expect(modal).toBeVisible();
    const panels: Record<string, string> = {};
    for (const [section, leaves] of Object.entries(sections)) {
      await modal.getByLabel('Decision Trace sections', {exact:true}).getByRole('button', {name:new RegExp('^'+section)}).click();
      const reveal = modal.getByRole('button', {name:'Show empty panels', exact:true});
      if (await reveal.isVisible()) await reveal.click();
      for (const leaf of leaves) {
        await modal.getByTestId('trace-leaf-'+leaf).click();
        const panel = modal.getByRole('tabpanel');
        await expect(panel).not.toContainText(/Loading .*\.\.\./, {timeout:15_000});
        await expect(panel).not.toBeEmpty();
        panels[leaf] = await panel.innerText();
        if (leaf === 'summary') await expect(panel).toContainText(terminal.decision_trace_id);
        if (leaf === 'audit') await expect(panel.getByTestId('recorded-turn-history')).toBeVisible();
        if (leaf === 'audit' && operations.size === 4) {
          const history = panel.getByTestId('recorded-turn-history');
          await history.getByLabel('Recorded turn revision').selectOption({label:`Revision ${previousTerminal.case_revision}`});
          await expect(history).toContainText(previousTerminal.operation_id);
          await expect(history).not.toContainText(terminal.operation_id);
          await history.getByLabel('Recorded turn revision').selectOption({label:`Revision ${terminal.case_revision}`});
          await expect(history).toContainText(terminal.operation_id);
          await expect(history).toContainText('commerce authority: none');
        }
      }
    }
    expect(panels.raw).toContain(terminal.decision_trace_id);
    await info.attach(`turn-${operations.size}`, {body:JSON.stringify({terminal,panels}, null, 2), contentType:'application/json'});
    await modal.getByTitle('Close', {exact:true}).click();
    previousTerminal = terminal;
  }
  expect(dispatches).toEqual([]);
  expect(failures).toEqual([]);
});
