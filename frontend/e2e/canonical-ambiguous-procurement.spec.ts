import { test, expect } from '@playwright/test';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';

function devApiKey(): string {
  if (process.env.VITE_API_KEY?.trim()) return process.env.VITE_API_KEY.trim();
  const here = dirname(fileURLToPath(import.meta.url));
  for (const rel of ['../.env.local', '../.env.development.local']) {
    try {
      const match = readFileSync(resolve(here, rel), 'utf8').match(/^VITE_API_KEY=(.*)$/m);
      if (match?.[1]?.trim()) return match[1].trim();
    } catch { /* try next */ }
  }
  return '';
}

async function send(page: import('@playwright/test').Page, text: string, captureChatResponse = false) {
  const input = page.getByPlaceholder('Type your message...');
  const responsePromise = captureChatResponse
    ? page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && /\/api\/v1\/shopping-cases\/interpretations(?:\?|$)/.test(response.url())
    ), { timeout: 20_000 })
    : null;
  await input.fill(text);
  await input.press('Enter');
  const response = responsePromise ? await responsePromise : null;
  if (response) expect(response.ok(), `chat request failed: ${response.status()}`).toBeTruthy();
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 20_000 });
  if (!response) return null;
  return response.json();
}

async function expectTraceEvent(
  page: import('@playwright/test').Page,
  traceId: string,
  eventType: string,
) {
  await expect.poll(async () => {
    const response = await page.request.get(`/api/v1/trace/${traceId}/events`);
    if (!response.ok()) return [];
    const body = await response.json();
    const events = Array.isArray(body) ? body : (body.events || []);
    return events.map((event: any) => event.event_type);
  }, { timeout: 30_000 }).toContain(eventType);
}

test('ambiguous workload explores locally before optional research without cart authority', async ({ page }) => {
  test.setTimeout(240_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}`;
  const uid = `enterprise-e2e-ambiguous-${suffix}`;
  await page.addInitScript((value) => sessionStorage.setItem('uid', value), uid);
  const key = devApiKey();
  expect(key).not.toEqual('');
  for (const [sku, quantity] of [['LAP-0003', 30], ['LAP-0004', 30]] as const) {
    const seeded = await page.request.put(`/api/v1/cart/items/${sku}`, {
      headers: { 'x-api-key': key, 'Content-Type': 'application/json' },
      data: { uid, sku, quantity, allow_sourcing: true },
    });
    expect(seeded.ok(), `cart seed failed for ${sku}`).toBeTruthy();
  }
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await send(page, 'Clear cart.');
  await expect(page.getByText(/cart is now empty/i)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Undo available.*2 prior line item/i)).toBeVisible();
  await expect(page.getByRole('button', { name: /Restore/i })).toBeVisible();

  const ambiguousTurn = await send(
    page,
    'I need a laptop for a digital twin project. It is for OT cyber-attack simulation.',
    true,
  );

  const interpretation = page.getByTestId('ambiguity-exploration');
  await expect(interpretation).toBeVisible({ timeout: 60_000 });
  await expect(interpretation.getByTestId('buyer-research-status'))
    .toContainText(/external research is off/i);
  await expect(interpretation.getByRole('button', { name: /research approved sources/i }))
    .toBeVisible();
  await expect(interpretation).toContainText(/upload requirements/i);
  await expect(interpretation).toContainText(/enter specifications/i);
  const accounting = page.getByTestId('ambiguity-accounting');
  await expect(accounting).toContainText(/external calls: 0/i);
  await expect(accounting).toContainText(/paid calls: 0/i);
  await expect(accounting).toContainText(/cart authority: none/i);

  const shelves = page.getByTestId('product-shelves');
  await expect(shelves).toBeVisible();
  await expect(page.getByText(/Provisional shortlist.*configuration/i)).toBeVisible();
  await expect(page.getByText(/^Found 0 products$/i)).toHaveCount(0);
  await expect(shelves).toContainText(/best across accepted shared needs/i);
  await expect(shelves).toContainText(/mobile workstation/i);
  expect(ambiguousTurn?.catalog_candidate_set).toMatchObject({
    status: 'eligible',
    taxonomy_handle: 'el-6-6',
    taxonomy_source: 'explicit_query',
    reason: 'query_specific_catalog_candidates',
  });
  await expect(shelves).not.toContainText(/desktop workstation/i);
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  const traceId = ambiguousTurn?.trace_id;
  expect(traceId).toBeTruthy();
  await expectTraceEvent(page, traceId, 'ambiguity_exploration_projected');
});
