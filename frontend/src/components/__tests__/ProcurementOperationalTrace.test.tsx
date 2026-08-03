import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ProcurementOperationalTrace from '../ProcurementOperationalTrace';


const VIEW = {
  authority: 'shadow_allocation',
  execution_authority: 'legacy_inventory_reservations',
  summary: {
    committed_quantity: 80,
    allocated_quantity: 53,
    shortfall_quantity: 27,
    allocation_pressure: 0.3375,
    oldest_queue_age_seconds: 720,
  },
  sourcing_batches: [{
    batch_ref: 'Batch b-27', quantity: 27, child_demand_count: 3, status: 'draft',
  }],
  supplier_pressure: [{
    supplier_id: 'SUP-1', supplier_facility_id: 'FAC-SYD', status: 'watch',
    external_contact_authority: 'governed', reason_codes: [],
    queue: {
      open_requests: 3, open_units: 80, dispatches_last_hour: 2,
      open_request_utilization: 0.75, open_unit_utilization: 0.8,
      dispatch_utilization: 0.667,
    },
    response_sla: { seconds: 7200, queue_age_seconds: 3600, status: 'within_sla' },
    source_health: {
      status: 'fresh', source_id: 'portal-adapter', source_version: 'snapshot-7',
      observed_at: '2026-08-03T11:00:00+00:00', expires_at: '2026-08-03T13:00:00+00:00',
    },
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
    privacy: { status: 'not_required' }, state_prevented: null,
  }],
};


describe('ProcurementOperationalTrace', () => {
  it('renders allocation, supplier pressure, wave economics and route evidence without overclaiming', () => {
    render(<ProcurementOperationalTrace allocationView={VIEW} />);

    expect(screen.getByText('Shadow allocation')).toBeInTheDocument();
    expect(screen.getByText(/27 unconfirmed unit\(s\) cannot become a delivery promise/)).toBeInTheDocument();
    expect(screen.getByText(/3 anonymized child demand/)).toBeInTheDocument();

    const pressure = screen.getByTestId('proc-supplier-pressure');
    expect(within(pressure).getByText(/SUP-1 \/ FAC-SYD/)).toBeInTheDocument();
    expect(within(pressure).getByText(/80% open-unit envelope/)).toBeInTheDocument();
    expect(within(pressure).getByText(/Response SLA: within SLA/)).toBeInTheDocument();
    expect(within(pressure).getByText(/portal-adapter · snapshot-7 · fresh/)).toBeInTheDocument();
    expect(within(pressure).getByText(/New supplier contact: governed/)).toBeInTheDocument();

    expect(screen.getByText(/Estimated freight saving AUD 90/)).toBeInTheDocument();
    expect(screen.getByText(/ETA 5–8 days · calculated range, not a promise/)).toBeInTheDocument();
    expect(screen.getByText(/dispatch 1–2d · transit 2–3d · inspection 1–2d/)).toBeInTheDocument();
  });

  it('renders stale supplier state as blocked rather than healthy', () => {
    const stale = {
      ...VIEW,
      supplier_pressure: [{
        ...VIEW.supplier_pressure[0], status: 'degraded',
        external_contact_authority: 'blocked', reason_codes: ['supplier_queue_stale'],
        source_health: { ...VIEW.supplier_pressure[0].source_health, status: 'stale' },
      }],
    };
    render(<ProcurementOperationalTrace allocationView={stale} />);
    const pressure = screen.getByTestId('proc-supplier-pressure');
    expect(within(pressure).getByText(/New supplier contact: blocked/)).toBeInTheDocument();
    expect(within(pressure).getByText(/supplier queue stale/)).toBeInTheDocument();
  });
});
