import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import DecisionRunTracePanel from '../DecisionRunTracePanel';


describe('DecisionRunTracePanel', () => {
  it('shows unresolved conflicts and denies commercial authority', () => {
    render(<DecisionRunTracePanel status="ready" classNames={{ summaryPane: 'summary', empty: 'empty' }} data={{
      latest: {
        case_revision: 7,
        knowledge_cutoff: '2026-08-17T01:00:00+00:00',
        evaluation_time: '2026-08-27T01:00:00+00:00',
        stage_receipts: [{
          stage_id: 'stage-commercial', stage: 'commercial', status: 'completed',
          tool_selection_receipts: [{
            capability: 'inventory_availability', outcome: 'selected',
            selected_deployment_ids: ['commerce_catalog.inventory_level'],
          }],
        }],
        evidence_watermarks: [{
          source: 'case_interpretation:sci-1', state: 'current',
          observed_at: '2026-08-17T00:00:00Z', source_version: 'plan-1',
        }],
        temporal_conflicts: [{
          conflict_id: 'tcr-abc', subject: 'offer:preferred', attribute: 'lead_time_days',
          status: 'unresolved', resolution_owner: 'supplier',
        }],
        invalidations: [{ code: 'changed', changed_path: 'requested_quantity', invalidated_stages: ['commercial', 'fulfilment'] }],
      },
      dependency_edges: [{ edge_id: 'edge-1', source_ref: 'inventory:current', target_ref: 'stage:commercial', relation: 'consumed_by' }],
      views: {
        canonical_truth: {
          research_execution: 'COMPLETE', evidence_status: 'ACCEPTED_COMPLETE',
          freshness: 'CURRENT', decision_status: 'QUALIFIED', commerce_authority: 'NONE',
          external_calls: 2, paid_calls: 0, cart_mutations: 0, supplier_sends: 0,
        },
        what_changed: { from_revision: 6, to_revision: 7, invalidation_count: 1 },
        what_was_known_then: { knowledge_cutoff: '2026-08-17T01:00:00+00:00', future_evidence_excluded: true },
        who_can_fulfil_now: {
          evidence_warning: 'Latest evidence, not a live stock promise.',
          allocation_projection: { allocated_units: 12, shortfall_units: 18 },
          commercial_decision: { status: 'QUALIFIED_PARTIAL', quantity_outcome: 'partial', budget_outcome: 'within' },
          supplier_candidates: [{ supplier_reference: 'supplier-a', quantity_available: 12, offered_sku: 'SKU-A', response_status: 'conditional' }],
        },
      },
    }} />);
    expect(screen.getByTestId('decision-run-trace')).toHaveTextContent('Revision 7');
    expect(screen.getByText(/Commerce authority: none/)).toBeInTheDocument();
    expect(screen.getByTestId('canonical-procurement-truth')).toHaveTextContent(
      /Research COMPLETE; evidence ACCEPTED_COMPLETE; freshness CURRENT; decision QUALIFIED/i,
    );
    expect(screen.getByText(/lead_time_days: unresolved/)).toBeInTheDocument();
    expect(screen.getByText(/requested_quantity invalidated commercial, fulfilment/)).toBeInTheDocument();
    expect(screen.getByText(/ToolScope inventory_availability: selected/i)).toBeInTheDocument();
    expect(screen.getByText(/case_interpretation:sci-1: current/i)).toBeInTheDocument();
    expect(screen.getByTestId('decision-record-view')).toHaveTextContent('Revision 6 → 7');
    fireEvent.click(screen.getByRole('button', { name: 'What was known then?' }));
    expect(screen.getByTestId('decision-record-view')).toHaveTextContent('Future evidence is excluded');
    fireEvent.click(screen.getByRole('button', { name: 'Who can fulfil now?' }));
    expect(screen.getByTestId('decision-record-view')).toHaveTextContent('12 allocated; 18 shortfall');
    expect(screen.getByTestId('decision-record-view')).toHaveTextContent('Commercial decision: QUALIFIED_PARTIAL');
    expect(screen.getByTestId('decision-record-view')).toHaveTextContent('supplier-a: 12 × SKU-A; conditional');
  });
});
