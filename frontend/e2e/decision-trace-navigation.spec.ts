import { expect, test } from '@playwright/test';

const leaves = [
  'summary', 'events', 'execution',
  'why', 'intent', 'memory', 'complexity',
  'evidence', 'multimodal', 'security',
  'market', 'procurement',
  'audit', 'raw',
] as const;

function tracePayload(traceId: string) {
  return {
    trace_id: traceId,
    events: [
      {
        id: 'query',
        seq: 1,
        event_type: 'query_received',
        timestamp: '2026-07-31T00:00:00Z',
        payload: { summary: 'Buyer requirement observed', intent: 'compare products' },
      },
      {
        id: 'memory',
        seq: 2,
        event_type: 'memory_retrieved',
        timestamp: '2026-07-31T00:00:01Z',
        payload: { summary: 'Session-scoped preference recalled' },
      },
      {
        id: 'market',
        seq: 3,
        event_type: 'market_projection',
        timestamp: '2026-07-31T00:00:02Z',
        payload: {
          sku: 'DEMO-1',
          status: 'advisory',
          source_status: { sales: 'complete', inventory: 'complete' },
          simulation_only: true,
        },
      },
      {
        id: 'security',
        seq: 4,
        event_type: 'supplier_response_quarantined',
        timestamp: '2026-07-31T00:00:03Z',
        payload: { reason: 'active_content', state_changed: false },
      },
      {
        id: 'multimodal',
        seq: 5,
        event_type: 'multimodal_evidence_assessed',
        timestamp: '2026-07-31T00:00:04Z',
        payload: { summary: 'Image evidence assessed' },
      },
    ],
    model_selection: { tier: 2, complexity: 0.4 },
    execution_steps: [{ kind: 'policy_gate', authority: 'authorizes', status: 'passed' }],
  };
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    class StableEventSource {
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      constructor() {
        window.setTimeout(() => this.onopen?.(new Event('open')), 0);
      }
      close() {}
      addEventListener() {}
      removeEventListener() {}
      dispatchEvent() { return true; }
      readonly readyState = 1;
      readonly url = '';
      readonly withCredentials = false;
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
    }
    Object.defineProperty(window, 'EventSource', { value: StableEventSource, configurable: true });
  });
  await page.route('**/api/v1/decisions/trace-nav/**', async (route) => {
    const url = route.request().url();
    if (url.endsWith('/audit-trail')) {
      await route.fulfill({ json: { hash_chain: [], retention_policy: {} } });
      return;
    }
    if (url.endsWith('/explain') || url.endsWith('/replay')) {
      await route.fulfill({ json: {} });
      return;
    }
    await route.fulfill({ json: tracePayload('trace-nav') });
  });
  await page.route('**/api/v1/decisions/trace-nav', async (route) => {
    await route.fulfill({ json: tracePayload('trace-nav') });
  });
  await page.route('**/api/v1/fulfillment/**', async (route) => {
    await route.fulfill({ status: 404, json: { detail: 'No case in navigation fixture' } });
  });
});

test('consolidated Decision Trace preserves requests, keyboard use, and every deep link', async ({ page }) => {
  const decisionRequests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/api/v1/decisions/trace-nav') decisionRequests.push(request.url());
  });

  await page.goto('/?trace=trace-nav&tracetab=summary');
  await expect(page.getByTestId('trace-trust-strip')).toBeVisible();
  await expect(page.getByLabel('Decision Trace section', { exact: true })).toBeAttached();
  await page.waitForTimeout(250);
  const initialRequests = decisionRequests.length;

  for (const section of ['Reasoning', 'Evidence & Risk', 'Commercial Journey']) {
    await page.getByRole('button', { name: new RegExp(`^${section}`) }).click();
  }
  expect(decisionRequests).toHaveLength(initialRequests);

  await page.getByRole('button', { name: 'Decision', exact: true }).click();
  await expect(page.getByTestId('trace-leaf-summary')).toHaveAttribute('aria-selected', 'true');
  await page.getByTestId('trace-leaf-summary').focus();
  await page.keyboard.press('End');
  await expect(page.getByTestId('trace-leaf-execution')).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('Home');
  await expect(page.getByTestId('trace-leaf-summary')).toHaveAttribute('aria-selected', 'true');

  for (const leaf of leaves) {
    await page.goto(`/?trace=trace-nav&tracetab=${leaf}`);
    await expect(page.getByTestId(`trace-leaf-${leaf}`)).toHaveAttribute('aria-selected', 'true');
  }
});
