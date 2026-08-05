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
      {
        id: 'semantic-resolution',
        seq: 6,
        event_type: 'recommendation_result',
        timestamp: '2026-07-31T00:00:05Z',
        payload: {
          products_summary: [],
          semantic_resolution: {
            outcome: 'proceed_catalog',
            catalog_authority: 'permitted',
            residual_route: 'AUTHORIZE',
            residual_reasons: ['consequential_action_requires_policy'],
            authorization_granted: false,
            desired_outcome: 'source hotel chairs made from the requested material',
            concepts: [{ text: 'iron birch', status: 'resolved' }],
            questions: [],
            state_prevented: [],
            next_permitted_action: 'evaluate_consequential_action_policy',
          },
          catalog_alignment: { status: 'qualified_catalog_match', qualified: ['DEMO-ALT-1'] },
          case_obligations: [{
            kind: 'buyer_commitment', status: 'authorization_required',
            authorization_granted: false, residual_route: 'AUTHORIZE',
            selected_sku: 'DEMO-ALT-1', quantity: 20,
            atp_snapshot: { source_version: 'ATP-FIXTURE-42', observed_at: '2026-07-31T00:00:04Z' },
          }],
          semantic_evidence: {
            selected: ['concept_resolution'],
            legs: { concept_resolution: { data: {
              status: 'evidence_candidates',
              authority: 'evidence_candidate_only',
              query: 'iron birch definition requirements compatibility',
              query_hash: 'fixture-query-01',
              provider_id: 'approved_search_proxy',
              provider_run_status: 'cached',
              cache_status: 'hit',
              source_status: { status: 'full', hit_count: 1, latency_ms: 17 },
              items: [{
                title: 'Material identity reference',
                source_domain: 'docs.example.org',
                url: 'https://docs.example.org/materials/iron-birch',
                fetched_ts: 1785859200,
              }],
            } } },
          },
        },
      },
      {
        id: 'return-claim-1', seq: 7, event_type: 'return_claim_evidence_pending',
        source_id: 'Returns_Agent', timestamp: '2026-08-04T01:00:00Z',
        payload: {
          claim_id: 'claim-1', status: 'evidence_pending', order_verification_status: 'found',
          evidence_count: 2, evidence_status: 'pending_security_review',
          authority: 'observation_only', commercial_action_prevented: true,
        },
      },
      {
        id: 'return-claim-2', seq: 8, event_type: 'return_claim_under_review',
        source_id: 'Returns_Agent', timestamp: '2026-08-04T01:03:00Z',
        payload: {
          claim_id: 'claim-1', status: 'under_review', order_verification_status: 'found',
          evidence_count: 2, evidence_status: 'clean', authority: 'human_review_required',
          commercial_action_prevented: true,
        },
      },
    ],
    intent_analysis: {
      semantic_resolution: {
        outcome: 'proceed_catalog',
        catalog_authority: 'permitted',
        residual_route: 'AUTHORIZE',
        residual_reasons: ['consequential_action_requires_policy'],
        authorization_granted: false,
        desired_outcome: 'source hotel chairs made from the requested material',
        concepts: [{ text: 'iron birch', status: 'resolved' }],
        questions: [],
        state_prevented: [],
        next_permitted_action: 'evaluate_consequential_action_policy',
      },
    },
    catalog_alignment: { status: 'qualified_catalog_match', qualified: ['DEMO-ALT-1'] },
    case_obligations: [{
      kind: 'buyer_commitment', status: 'authorization_required',
      authorization_granted: false, residual_route: 'AUTHORIZE',
      selected_sku: 'DEMO-ALT-1', quantity: 20,
      atp_snapshot: { source_version: 'ATP-FIXTURE-42', observed_at: '2026-07-31T00:00:04Z' },
    }],
    semantic_evidence: {
      selected: ['concept_resolution'],
      legs: { concept_resolution: { data: {
        status: 'evidence_candidates',
        authority: 'evidence_candidate_only',
        query: 'iron birch definition requirements compatibility',
        query_hash: 'fixture-query-01',
        provider_id: 'approved_search_proxy',
        provider_run_status: 'cached',
        cache_status: 'hit',
        source_status: { status: 'full', hit_count: 1, latency_ms: 17 },
        items: [{
          title: 'Material identity reference',
          source_domain: 'docs.example.org',
          url: 'https://docs.example.org/materials/iron-birch',
          fetched_ts: 1785859200,
        }],
      } } },
    },
    products: [{ sku: 'DEMO-ALT-1', name: 'Evidence-qualified alternative' }],
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
    if (leaf === 'why') {
      const semantic = page.getByTestId('semantic-resolution-trace');
      await expect(semantic).toContainText('iron birch');
      await expect(semantic).toContainText('iron birch definition requirements compatibility');
      await expect(semantic).toContainText('approved search proxy');
      await expect(semantic).toContainText('candidate only');
      await expect(semantic.getByRole('link', { name: 'Material identity reference' }))
        .toHaveAttribute('href', 'https://docs.example.org/materials/iron-birch');
      await expect(semantic).toContainText('qualified catalog match');
      await expect(page.getByText('Score not recorded')).toBeVisible();
    }
    if (leaf === 'procurement') {
      const lifecycle = page.getByTestId('return-lifecycle-trace');
      await expect(lifecycle).toContainText('Under human review');
      await expect(lifecycle).toContainText('Authenticated order matched');
      await expect(lifecycle).toContainText(/no refund, replacement or repair authorization/i);
    }
  }
});

test('qualified evidence chain remains visibly human gated', async ({ page }) => {
  await page.goto('/?trace=trace-nav&tracetab=why');
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal).toBeVisible();
  const authority = modal.getByTestId('semantic-commercial-authority');
  await expect(authority).toContainText(/qualified catalog match/i);
  await expect(authority).toContainText('DEMO-ALT-1');
  await expect(authority).toContainText('ATP-FIXTURE-42');
  await expect(authority).toContainText(/authorization required/i);
  await expect(authority).toContainText(/not granted/i);
});
