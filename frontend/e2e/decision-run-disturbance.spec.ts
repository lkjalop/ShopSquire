import { expect, test } from '@playwright/test';


test('inventory disturbance projects selective invalidation and unresolved delivery conflict', async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem('uid', 'buyer-disturbance');
    window.sessionStorage.setItem('tenant_id', 'portfolio');
  });
  const trace = {
    trace_id: 'trace-disturbance',
    events: [{
      id: 'run-2', seq: 1, event_type: 'procurement_decision_run_recorded',
      timestamp: '2026-08-17T09:05:00Z',
      payload: { procurement_decision_run: { case_id: 'case-disturbance', case_revision: 2 } },
    }],
  };
  await page.route('**/api/v1/decisions/trace-disturbance/**', (route) => route.fulfill({ json: {} }));
  await page.route('**/api/v1/decisions/trace-disturbance', (route) => route.fulfill({ json: trace }));
  await page.route('**/api/v1/trace/trace-disturbance/events**', (route) => route.fulfill({ json: trace }));
  await page.route('**/api/v1/shopping-cases/case-disturbance/decision-runs**', (route) => route.fulfill({ json: {
    schema_version: 'shopping-case-decision-runs-v1', case_id: 'case-disturbance', history_count: 2,
    latest: {
      run_id: 'pdr-current', case_revision: 2, status: 'completed',
      knowledge_cutoff: '2026-08-17T09:05:00+00:00', evaluation_time: '2026-08-27T00:00:00+00:00',
      commercial_authority_granted: false,
      stage_receipts: [
        { stage_id: 'stage-fit', stage: 'fit', status: 'completed' },
        { stage_id: 'stage-commercial', stage: 'commercial', status: 'completed' },
        { stage_id: 'stage-fulfilment', stage: 'fulfilment', status: 'degraded', reason_code: 'lead_time_conflict' },
      ],
      invalidations: [{ code: 'case_state_changed', changed_path: 'inventory.current', invalidated_stages: ['commercial', 'fulfilment', 'response'] }],
      temporal_conflicts: [{
        conflict_id: 'tcr-one', subject: 'offer:preferred', attribute: 'lead_time_days',
        status: 'unresolved', resolution_owner: 'supplier',
      }],
      evidence_watermarks: [],
    },
    history: [],
    dependency_edges: [
      { edge_id: 'e1', source_ref: 'inventory:current', target_ref: 'stage:stage-commercial', relation: 'consumed_by' },
      { edge_id: 'e2', source_ref: 'stage:stage-commercial', target_ref: 'commercial:shelves', relation: 'produced_by' },
    ],
    authority: 'decision_evidence_only',
  } }));
  await page.route('**/api/v1/decisions/trace-disturbance/audit-trail', (route) => route.fulfill({ json: {} }));

  await page.goto('/?trace=trace-disturbance&tracetab=audit');
  const panel = page.getByTestId('decision-run-trace');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('Revision 2');
  await expect(panel).toContainText('fit: completed');
  await expect(panel).toContainText('fulfilment: degraded (lead_time_conflict)');
  await expect(panel).toContainText('inventory.current invalidated commercial, fulfilment, response');
  await expect(panel).toContainText('lead_time_days: unresolved; resolution owner supplier');
  await expect(panel).toContainText('Commerce authority: none');
});
