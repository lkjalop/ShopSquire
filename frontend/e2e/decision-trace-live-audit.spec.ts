import { expect, test } from '@playwright/test';
import { registerBuyer } from './helpers/registeredBuyer';

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

test('live Decision Trace is durable, factual, and honest across all leaves', async ({ page: buyerPage, browser }) => {
  test.setTimeout(180_000);
  const uid = await registerBuyer(buyerPage.context());
  const query = 'show gaming laptops between 1500 and 1900, exclude Apple';

  const seeded = await buyerPage.request.post('/api/v1/chat/query', {
    data: { uid, query },
    timeout: 60_000,
  });
  expect(seeded.ok(), `seed failed (${seeded.status()})`).toBeTruthy();
  const recommendation = await seeded.json();
  const traceId = String(recommendation.trace_id || recommendation.decision_trace_id || '');
  expect(traceId).not.toBe('');

  const key = process.env.OWNER_API_KEY;
  if (!key) throw new Error('The owned audit profile requires its explicit operator key');
  const operator = await browser.newContext({extraHTTPHeaders: {
    'x-api-key': key, 'x-tenant-id': process.env.VITE_STOREFRONT_TENANT_ID!,
  }});
  const page = await operator.newPage();
  await page.addInitScript(value => {
    sessionStorage.setItem('role', 'owner');
    sessionStorage.setItem('ss_owner_key', value);
  }, key);
  try {
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
  } finally { await operator.close(); }
});
