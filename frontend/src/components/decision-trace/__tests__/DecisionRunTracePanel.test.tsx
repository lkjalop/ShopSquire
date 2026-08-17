import { render, screen } from '@testing-library/react';
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
    }} />);
    expect(screen.getByTestId('decision-run-trace')).toHaveTextContent('Revision 7');
    expect(screen.getByText(/Commerce authority: none/)).toBeInTheDocument();
    expect(screen.getByText(/lead_time_days: unresolved/)).toBeInTheDocument();
    expect(screen.getByText(/requested_quantity invalidated commercial, fulfilment/)).toBeInTheDocument();
    expect(screen.getByText(/ToolScope inventory_availability: selected/i)).toBeInTheDocument();
    expect(screen.getByText(/case_interpretation:sci-1: current/i)).toBeInTheDocument();
  });
});
