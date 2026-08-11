import { expect, test } from '@playwright/test';

const leaves = [
  'summary', 'events', 'execution',
  'research', 'why', 'intent', 'memory', 'complexity',
  'evidence', 'multimodal', 'security',
  'market', 'procurement', 'audit', 'raw',
] as const;

const forbiddenDemoText = /lorem|coming soon|placeholder|trace snapshot is not available|Ã|Â|â€|ï¿½|�/i;

const sectionForLeaf: Record<(typeof leaves)[number], string> = {
  summary: 'Decision', events: 'Decision', execution: 'Decision',
  research: 'Research & Fit', why: 'Research & Fit',
  intent: 'Reasoning', memory: 'Reasoning', complexity: 'Reasoning',
  evidence: 'Evidence & Risk', multimodal: 'Evidence & Risk', security: 'Evidence & Risk',
  market: 'Commercial Journey', procurement: 'Commercial Journey',
  audit: 'Advanced technical details', raw: 'Advanced technical details',
};

test('live Decision Trace is durable, factual, and honest across all leaves', async ({ page }) => {
  test.setTimeout(180_000);
  const uid = `e2e-live-trace-${Date.now()}`;
  const query = 'show gaming laptops between 1500 and 1900, exclude Apple';

  const apiKey = process.env.E2E_API_KEY || process.env.VITE_API_KEY || 'local-merchant-key';
  const seeded = await page.request.get('/api/v1/recommend/suggest', {
    headers: { 'x-api-key': apiKey },
    params: { uid, query },
    timeout: 60_000,
  });
  expect(seeded.ok(), `seed failed (${seeded.status()})`).toBeTruthy();
  const recommendation = await seeded.json();
  const traceId = String(recommendation.trace_id || recommendation.decision_trace_id || '');
  expect(traceId).not.toBe('');

  await page.addInitScript((key) => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init: RequestInit = {}) => {
      const headers = new Headers(init.headers || {});
      headers.set('x-api-key', key);
      return originalFetch(input, { ...init, headers });
    };
  }, apiKey);

  await page.goto(`/?trace=${encodeURIComponent(traceId)}&tracetab=summary`);
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal).toBeVisible();
  await expect(modal.locator('[role="tabpanel"]')).not.toContainText('Waiting for the durable trace snapshot', { timeout: 30_000 });
  const revealEmpty = modal.getByRole('button', { name: 'Show empty panels' });
  if (await revealEmpty.isVisible().catch(() => false)) await revealEmpty.click();

  let activeSection = '';
  for (const leaf of leaves) {
    const section = sectionForLeaf[leaf];
    if (section !== activeSection) {
      await modal.getByRole('button', { name: new RegExp(`^${section.replace(/[&]/g, '\\&')}`) }).click();
      activeSection = section;
      const reveal = modal.getByRole('button', { name: 'Show empty panels' });
      if (await reveal.isVisible().catch(() => false)) await reveal.click();
    }
    await modal.getByTestId(`trace-leaf-${leaf}`).click();
    await expect(modal.getByTestId(`trace-leaf-${leaf}`)).toHaveAttribute('aria-selected', 'true');
    const panel = modal.locator('[role="tabpanel"]');
    await expect(panel).toBeVisible();
    await expect.poll(async () => (await panel.innerText()).trim().length).toBeGreaterThan(20);
    const text = await panel.innerText();
    expect(text, `${leaf} contains demo placeholder or encoding corruption`).not.toMatch(forbiddenDemoText);
  }

  const rawText = await modal.locator('[role="tabpanel"]').innerText();
  expect(rawText).toContain(traceId);
  expect(rawText.toLowerCase()).toContain('gaming');
  expect(rawText).toContain('1500');
  expect(rawText).toContain('1900');
});
