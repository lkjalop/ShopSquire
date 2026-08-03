import { expect, test } from '@playwright/test';


test('Commercial Journey renders governed supplier pressure, wave and route evidence', async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem('ss_owner_key', 'operator-test-key');
  });
  await page.route('**/api/v1/decisions/trace-proc-ops/**', async (route) => {
    await route.fulfill({ json: {} });
  });
  await page.route('**/api/v1/decisions/trace-proc-ops', async (route) => {
    await route.fulfill({ json: {
      trace_id: 'trace-proc-ops',
      events: [{
        id: 'proc-1', seq: 1, event_type: 'procurement_case_opened',
        source_id: 'Procurement_Agent', timestamp: '2026-08-03T12:00:00Z',
        payload: { summary: 'Sourcing shortfall assessed' },
      }],
      execution_steps: [{ kind: 'policy_gate', authority: 'authorizes', status: 'passed' }],
    } });
  });
  await page.route('**/api/v1/fulfillment/cases/by-trace/trace-proc-ops/all/operator-view', async (route) => {
    await route.fulfill({ json: { cases: [{
      case_id: 'case-ops-1', state: 'AWAITING_APPROVAL',
      state_json: { availability: { item_ref: 'SKU-1' } },
    }] } });
  });
  await page.route('**/api/v1/fulfillment/cases/case-ops-1/journey', async (route) => {
    await route.fulfill({ json: { journey: [] } });
  });
  await page.route('**/api/v1/admin/allocation/workbench?sku=SKU-1', async (route) => {
    await route.fulfill({ json: {
      authority: 'shadow_allocation', execution_authority: 'legacy_inventory_reservations',
      summary: {
        committed_quantity: 80, allocated_quantity: 53, shortfall_quantity: 27,
        allocation_pressure: 0.3375, oldest_queue_age_seconds: 720,
      },
      sourcing_batches: [{
        batch_ref: 'Batch b-27', quantity: 27, child_demand_count: 3, status: 'draft',
      }],
      supplier_pressure: [{
        supplier_id: 'SUP-1', supplier_facility_id: 'FAC-SYD', status: 'watch',
        external_contact_authority: 'governed', reason_codes: [],
        queue: { open_requests: 3, open_units: 80, dispatches_last_hour: 2,
          open_unit_utilization: 0.8 },
        response_sla: { seconds: 7200, queue_age_seconds: 3600, status: 'within_sla' },
        source_health: { status: 'fresh', source_id: 'portal-adapter', source_version: 'snapshot-7' },
      }],
      sourcing_waves: [{
        wave_ref: 'Wave w-1', supplier_id: 'SUP-1', supplier_facility_id: 'FAC-SYD',
        batch_count: 2, total_quantity: 27, currency: 'AUD', incoterm: 'DAP',
        estimated_savings_cents: 9000,
      }],
      route_proposals: [{
        proposal_ref: 'Route r-1', mode: 'merchant_inspected', status: 'eligible',
        eta_days: { min: 5, max: 8 },
        components: { dispatch_days: [1, 2], transit_days: [2, 3], inspection_days: [1, 2] },
        privacy: { status: 'not_required' },
      }],
      disruption_impacts: [{
        observation_id: 'obs-customs-1', disruption_type: 'customs_system_outage',
        status: 'bounded_recalculation_proposed', claim_status: 'supported', severity: 'high',
        authority: 'proposal_only', state_prevented: 'commercial_state_mutation',
        evidence: {
          source_id: 'official-customs', source_revision: 'r3',
          source_licence: 'official-open-data-v1', evidence_ref: 'sha256:evidence-42',
          claim_status: 'supported',
        },
        dependency_path: { edges: [
          { from_node_id: 'variant:SKU-1', to_node_id: 'facility:shanghai' },
          { from_node_id: 'facility:shanghai', to_node_id: 'lane:cn-syd' },
        ] },
        impact: {
          eta_days: { before: { low: 5, high: 8 }, proposed: { low: 8, high: 16 } },
          freight_cost_minor: { before: { low: 5000, high: 7000 }, proposed: { low: 7000, high: 12000 } },
          contribution_margin: { before: 0.25, proposed: { low: 0.21, high: 0.24 } },
        },
        proposals: [
          { type: 'buyer_promise_review', state: 'proposed_not_applied', eta_days: { low: 8, high: 16 } },
          { type: 'payment_authorization_review', state: 'review_required', proposed_capture_minor: 0 },
        ],
      }],
      temporal_cache_lifecycle: {
        scope: 'tenant_operator_summary', case_specific: false, stale_content_served: false,
        entries: [{
          cache_key: 'cache:v2:agentic_rag_retrieval:demo', namespace: 'agentic_rag_retrieval',
          status: 'rebuild_queued', current_generation: 1, source_version: 'faq-v1',
          rebuild_job_id: 'job-1', rebuild_status: 'queued', servable: false,
        }],
      },
    } });
  });

  await page.goto('/?trace=trace-proc-ops&tracetab=procurement');
  const trace = page.getByRole('dialog', { name: /Decision Trace/i });
  await expect(trace.getByTestId('proc-allocation-trace')).toBeVisible();
  await expect(trace.getByTestId('proc-supplier-pressure')).toContainText('SUP-1 / FAC-SYD');
  await expect(trace.getByTestId('proc-supplier-pressure')).toContainText('Response SLA: within SLA');
  await expect(trace.getByTestId('proc-supplier-pressure')).toContainText('portal-adapter · snapshot-7 · fresh');
  await expect(trace.getByTestId('proc-sourcing-wave')).toContainText('Estimated freight saving AUD 90');
  await expect(trace.getByTestId('proc-route-proposal')).toContainText('ETA 5–8 days');
  await expect(trace.getByText(/27 unconfirmed unit\(s\) cannot become a delivery promise/)).toBeVisible();
  await expect(trace.getByTestId('proc-active-disruption')).toContainText('customs system outage');
  await expect(trace.getByTestId('proc-disruption-path')).toContainText('variant:SKU-1');
  await expect(trace.getByTestId('proc-disruption-impact')).toContainText('ETA 5');
  await expect(trace.getByTestId('proc-revised-promise')).toContainText('proposed not applied');
  await expect(trace.getByTestId('proc-payment-effect')).toContainText('capture remains 0');
  await expect(trace.getByTestId('proc-temporal-cache')).toContainText('rebuild queued');
  await expect(trace.getByTestId('proc-temporal-cache')).toContainText('not evidence for this case');
});
