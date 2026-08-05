import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AllocationWorkbench from './AllocationWorkbench';
import { fetchAllocationWorkbench } from '../../api';

vi.mock('../../api', () => ({ fetchAllocationWorkbench: vi.fn() }));

describe('AllocationWorkbench', () => {
  beforeEach(() => {
    vi.mocked(fetchAllocationWorkbench).mockResolvedValue({
      tenant_id: 't1', authority: 'shadow_allocation',
      execution_authority: 'legacy_inventory_reservations',
      summary: { committed_quantity: 80, allocated_quantity: 53, shortfall_quantity: 27,
        supplier_confirmed_quantity: 18, supplier_unresolved_quantity: 9,
        allocation_pressure: 0.3375, oldest_queue_age_seconds: 720 },
      metric_evidence: {
        allocation_pressure: { metric: 'allocation_pressure', value: 0.3375, unit: 'ratio',
          formula: 'shortfall_quantity / committed_quantity', numerator: 27, denominator: 80,
          source: 'demand_commitment + demand_allocation', source_record_count: 1,
          authority: 'shadow_allocation', status: 'calculated', calculated_at: '2026-08-02T01:00:00Z',
          window: { kind: 'current_projection', start: '2026-08-02T00:48:00Z', end: '2026-08-02T01:00:00Z' },
          trend_status: 'not_materialized', reason: 'historical_snapshots_not_materialized' },
        allocated_quantity: { metric: 'allocated_quantity', value: 53, unit: 'units',
          formula: "sum(allocation.quantity where status = 'allocated')", numerator: 53, denominator: null,
          source: 'demand_allocation', source_record_count: 1, authority: 'shadow_allocation',
          status: 'observed', calculated_at: '2026-08-02T01:00:00Z',
          window: { kind: 'current_projection', start: '2026-08-02T00:48:00Z', end: '2026-08-02T01:00:00Z' },
          trend_status: 'not_materialized', reason: 'historical_snapshots_not_materialized' },
      },
      demands: [{ demand_ref: 'Demand abc12345', case_ref: 'Case def67890', sku: 'RGAM-0007',
        destination_id: 'SYD', stage: 'committed', requested_quantity: 80,
        allocated_quantity: 53, shortfall_quantity: 27, priority_tier: 50,
        queue_age_seconds: 720, promise_state: 'partial', alternatives_required: true }],
      sourcing_batches: [{ batch_ref: 'Batch batch123', sku: 'RGAM-0007', destination_id: 'SYD',
        status: 'draft', quantity: 27, window_ends_at: '2026-08-02T01:00:00Z',
        child_demand_count: 3 }],
      sourcing_waves: [{ wave_ref: 'Wave wave1234', supplier_id: 'SUP-1',
        supplier_facility_id: 'SUP-SYD-DC', currency: 'AUD', incoterm: 'DAP',
        merchant_destination_id: 'merchant:SYD', status: 'draft',
        window_ends_at: '2026-08-02T02:00:00Z', standalone_freight_cents: 28000,
        consolidated_freight_cents: 17000, handling_cents: 2000,
        estimated_savings_cents: 9000, batch_count: 2, total_quantity: 37 }],
      route_proposals: [{ proposal_ref: 'Route route123', case_ref: 'Case case1234',
        mode: 'cross_dock', status: 'eligible', destination_token: 'DEST-SYD',
        eta_days: { min: 5, max: 8 }, components: {}, state_prevented: null,
        pii_release_authorized: false, created_at: '2026-08-02T01:00:00Z',
        privacy: { status: 'not_required' } }],
      privacy: { buyer_identities_exposed: false, child_demands_anonymized: true },
    } as any);
  });

  it('renders real ledger pressure, queue age and anonymized child counts', async () => {
    render(<AllocationWorkbench />);

    await waitFor(() => expect(screen.getByTestId('allocation-workbench')).toBeInTheDocument());
    expect(screen.getAllByText('80').length).toBeGreaterThan(0);
    expect(screen.getAllByText('53').length).toBeGreaterThan(0);
    expect(screen.getAllByText('27').length).toBeGreaterThan(0);
    expect(screen.getByText('Supplier confirmed')).toBeInTheDocument();
    expect(screen.getAllByText('18').length).toBeGreaterThan(0);
    expect(screen.getByText('Supplier unresolved')).toBeInTheDocument();
    expect(screen.getAllByText('9').length).toBeGreaterThan(0);
    expect(screen.getByText('34%')).toBeInTheDocument();
    expect(screen.getAllByText('12m').length).toBeGreaterThan(0);
    expect(screen.getByText(/3 anonymized child demand/)).toBeInTheDocument();
    expect(screen.getByText(/Estimated consolidation saving/)).toBeInTheDocument();
    expect(screen.getByText(/cross dock/)).toBeInTheDocument();
    expect(screen.getByText(/calculated range, not a promise/)).toBeInTheDocument();
    expect(screen.getByTestId('allocation-current-state-bar')).toHaveAttribute(
      'aria-label', '53 allocated, 27 shortfall from 80 committed units',
    );
    expect(screen.getByText('Metric evidence')).toBeInTheDocument();
    expect(screen.getByText(/Historical trend unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/shortfall_quantity \/ committed_quantity/)).toBeInTheDocument();
    expect(screen.getByText(/Denominator: 80/)).toBeInTheDocument();
    expect(screen.queryByText(/buyer@/i)).toBeNull();
  });

  it('fails visibly without replacing existing procurement execution', async () => {
    vi.mocked(fetchAllocationWorkbench).mockRejectedValueOnce(new Error('offline'));
    render(<AllocationWorkbench />);
    await waitFor(() => expect(screen.getByTestId('allocation-workbench-unavailable')).toBeInTheDocument());
    expect(screen.getByText(/Existing procurement execution is unchanged/)).toBeInTheDocument();
  });
});
