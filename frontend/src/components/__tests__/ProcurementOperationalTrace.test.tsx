import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ProcurementOperationalTrace, {
  DisruptionEvidenceTrace,
  TemporalCacheTechnicalTrace,
} from '../ProcurementOperationalTrace';


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
  promise_calculation: {
    calculation_version: 'promise-critical-path-v1', feasibility: 'unknown',
    requested_arrival_at: '2026-08-11T07:00:00+00:00', evaluated_at: '2026-08-04T00:00:00+00:00',
    quantity_by_deadline: 53, remaining_quantity: 27,
    earliest_arrival_range: {
      earliest: '2026-08-11T05:00:00+00:00', latest: '2026-08-12T03:00:00+00:00',
    },
    latest_viable_supplier_response_at: '2026-08-10T23:00:00+00:00',
    carrier_cutoff_at: '2026-08-11T03:00:00+00:00',
    failed_constraints: ['supplier_response_expectation_unknown'],
    state_prevented: 'unsupported_full_delivery_promise',
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
    temporal_response: {
      calendar_state: 'closed', sla_clock: 'paused', transmission_state: 'transmit_now',
      supplier_local_time: '2026-08-03T18:00:00+10:00',
      next_open_at: '2026-08-03T23:00:00+00:00',
      acknowledgement_due_at: '2026-08-04T01:00:00+00:00',
      quote_due_at: '2026-08-04T07:00:00+00:00',
      calendar_version: 'cal-7', policy_version: 'response-3', freshness: 'current',
    },
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
    const promise = screen.getByTestId('proc-promise-feasibility');
    expect(promise).toHaveTextContent('Quantity-by-deadline feasibilityunknown');
    expect(promise).toHaveTextContent('Feasible by deadline53 unit(s)');
    expect(promise).toHaveTextContent('Later or unconfirmed27 unit(s)');
    expect(promise).toHaveTextContent('Carrier cutoff: 2026-08-11T03:00:00+00:00');
    expect(promise).toHaveTextContent('State prevented: unsupported full delivery promise');
    expect(screen.getByText(/3 anonymized child demand/)).toBeInTheDocument();

    const pressure = screen.getByTestId('proc-supplier-pressure');
    expect(within(pressure).getByText(/SUP-1 \/ FAC-SYD/)).toBeInTheDocument();
    expect(within(pressure).getByText(/80% open-unit envelope/)).toBeInTheDocument();
    expect(within(pressure).getByText(/Response SLA: within SLA/)).toBeInTheDocument();
    const temporal = within(pressure).getByTestId('proc-temporal-response');
    expect(temporal).toHaveTextContent('Supplier calendar: closed · SLA clock paused');
    expect(temporal).toHaveTextContent('Supplier contact: transmit now');
    expect(temporal).toHaveTextContent('Acknowledgement due: 2026-08-04T01:00:00+00:00');
    expect(temporal).toHaveTextContent('Calendar cal-7 · policy response-3 · current');
    expect(within(pressure).getByText(/portal-adapter · snapshot-7 · fresh/)).toBeInTheDocument();
    expect(within(pressure).getByText(/New supplier contact: governed/)).toBeInTheDocument();

    expect(screen.getByText(/Estimated freight saving AUD 90/)).toBeInTheDocument();
    expect(screen.getByText(/ETA 5–8 days · calculated range, not a promise/)).toBeInTheDocument();
    expect(screen.getByText(/dispatch 1–2d · transit 2–3d · inspection 1–2d/)).toBeInTheDocument();
  });

  it('renders phone-only contact as queued rather than supplier contacted', () => {
    const queued = {
      ...VIEW,
      supplier_pressure: [{
        ...VIEW.supplier_pressure[0],
        temporal_response: {
          ...VIEW.supplier_pressure[0].temporal_response,
          transmission_state: 'queue_until_open',
        },
      }],
    };
    render(<ProcurementOperationalTrace allocationView={queued} />);
    const temporal = screen.getByTestId('proc-temporal-response');
    expect(temporal).toHaveTextContent('Supplier contact: contact queued until verified opening');
    expect(temporal).not.toHaveTextContent('supplier contacted');
  });

  it('renders durable contact, human-room and payment consequences without implying execution', () => {
    render(<ProcurementOperationalTrace allocationView={{
      ...VIEW,
      outbound_contact_schedule: {
        channel: 'phone', queue_state: 'queued_contact', transport_eligible: false,
        not_before: '2026-08-10T23:00:00+00:00', sla_clock: 'paused',
        schedule_reason: 'human_phone_contact_required',
      },
      human_room: { state: 'requested', assigned_operator_id: null, version: 1 },
      payment_consequence: {
        plan_type: 'deposit', status: 'deposit_authorization_required', currency: 'AUD',
        deposit_amount_cents: 20000, balance_amount_cents: 80000,
        state_prevented: 'balance_capture',
      },
    }} />);
    expect(screen.getByTestId('proc-contact-schedule')).toHaveTextContent('not executable by email worker');
    expect(screen.getByTestId('proc-human-room')).toHaveTextContent('requested');
    expect(screen.getByTestId('proc-payment-consequence')).toHaveTextContent('State prevented: balance capture');
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

  it('renders grounded recovery without presenting unknown stock as available', () => {
    render(<ProcurementOperationalTrace allocationView={{
      ...VIEW,
      recovery_options: [{
        batch_ref: 'Batch b-27', sku: 'RGAM-0007', status: 'options_available',
        state_prevented: 'unconfirmed_supply_presented_as_available', external_action: 'none',
        alternative_suppliers: [{
          supplier_id: 'SUP-2', supplier_name: 'Approved Supply Co',
          availability: 'unknown', action: 'request_confirmation',
        }],
        qualified_substitutes: [{
          sku: 'RGAM-0008', availability: 'unknown', action: 'request_confirmation',
        }],
      }],
    }} />);

    expect(screen.getByText('Grounded recovery options')).toBeInTheDocument();
    expect(screen.getByText(/Approved alternative · Approved Supply Co/)).toBeInTheDocument();
    expect(screen.getAllByText(/unknown ·/)).toHaveLength(2);
    expect(screen.getByText(/buyer consent required/)).toBeInTheDocument();
    expect(screen.getByText(/External action: none · confirmation remains required/)).toBeInTheDocument();
    expect(screen.queryByText(/available now/i)).not.toBeInTheDocument();
  });

  it('renders disruption provenance, impact, promise and payment effects as bounded evidence', () => {
    render(<ProcurementOperationalTrace allocationView={{
      ...VIEW,
      disruption_observations: [{
        observation_id: 'obs-1', disruption_type: 'customs_system_outage',
        claim_status: 'supported', severity: 'high', freshness: 'current',
        source: { source_id: 'ABF-ICS', source_version: 'notice-42', status: 'current' },
        dependency_path: ['Shanghai DC', 'Lane CN-SYD', 'RGAM-0007'],
        baseline: { eta_days: [7, 12], freight_cents: [12000, 12000], margin_pct: [15.4, 15.4] },
        revised: { eta_days: [10, 20], freight_cents: [12000, 31000], margin_pct: [11.2, 15.4] },
        buyer_promise: { status: 'review_required', affected_count: 3, revised_eta: '10–20 days' },
        payment_effect: { status: 'held', reason: 'supplier_confirmation_required' },
        contradictions: [{ source_id: 'carrier-1' }],
        state_changed: 'promise risk recorded',
      }],
    }} />);

    const disruption = screen.getByTestId('proc-active-disruption');
    expect(within(disruption).getByText(/customs system outage/)).toBeInTheDocument();
    expect(within(disruption).getByText(/ABF-ICS · notice-42 · current/)).toBeInTheDocument();
    expect(screen.getByTestId('proc-disruption-path')).toHaveTextContent('Shanghai DC → Lane CN-SYD → RGAM-0007');
    expect(screen.getByTestId('proc-disruption-impact')).toHaveTextContent('ETA 7–12 days → 10–20 days');
    expect(screen.getByTestId('proc-revised-promise')).toHaveTextContent('3 affected');
    expect(screen.getByTestId('proc-payment-effect')).toHaveTextContent('held · supplier confirmation required');
    expect(within(disruption).getByText(/external evidence cannot directly change allocation, payment, price or supplier contact/)).toBeInTheDocument();
  });

  it('accepts the canonical bounded disruption projection shape', () => {
    render(<ProcurementOperationalTrace allocationView={{
      ...VIEW,
      disruption_impacts: [{
        observation_id: 'obs-2', status: 'bounded_recalculation_proposed',
        evidence: { source_id: 'ABF-ICS', source_revision: 'notice-43', claim_status: 'supported' },
        dependency_path: { edges: [
          { from_node_id: 'variant:rgam-7', to_node_id: 'facility:shanghai' },
          { from_node_id: 'facility:shanghai', to_node_id: 'lane:cn-syd' },
        ] },
        impact: {
          eta_days: { before: { low: 7, high: 12 }, proposed: { low: 10, high: 20 } },
          freight_cost_minor: { before: { low: 50000, high: 60000 }, proposed: { low: 60000, high: 100000 } },
          contribution_margin: { before: 0.25, proposed: { low: 0.235, high: 0.245 } },
        },
        proposals: [
          { type: 'buyer_promise_review', state: 'proposed_not_applied', eta_days: { low: 10, high: 20 } },
          { type: 'payment_authorization_review', state: 'review_required', proposed_capture_minor: 0 },
        ],
        state_prevented: 'commercial_state_mutation',
      }],
    }} />);

    expect(screen.getByTestId('proc-disruption-path')).toHaveTextContent(
      'variant:rgam-7 → facility:shanghai → lane:cn-syd',
    );
    expect(screen.getByTestId('proc-disruption-impact')).toHaveTextContent(
      'ETA 7–12 days → 10–20 days · freight 50000–60000 → 60000–100000 · margin 25% → 23.5–24.5%',
    );
    expect(screen.getByTestId('proc-revised-promise')).toHaveTextContent('ETA 10–20 days');
    expect(screen.getByTestId('proc-payment-effect')).toHaveTextContent('review required · capture remains 0');
    expect(screen.getByText(/State prevented: commercial state mutation/)).toBeInTheDocument();
  });

  it('separates B2C and B2B counts without exposing buyer identity', () => {
    render(<ProcurementOperationalTrace allocationView={{
      ...VIEW,
      demands: [
        { demand_ref: 'Demand a1', buyer_type: 'b2c', buyer_name: 'Private Consumer' },
        { demand_ref: 'Demand a2', commerce_mode: 'b2b', account_name: 'Secret School' },
        { demand_ref: 'Demand a3', account_type: 'business' },
      ],
    }} />);

    const segments = screen.getByTestId('proc-buyer-segments');
    expect(segments).toHaveTextContent('B2C 1 · B2B 2 · buyer identities hidden');
    expect(segments).toHaveTextContent('sealed allocation policy');
    expect(segments).not.toHaveTextContent('Private Consumer');
    expect(segments).not.toHaveTextContent('Secret School');
  });

  it.each(['registered', 'stale', 'invalidated', 'rebuild_queued', 'rebuilding', 'degraded', 'rebuilt'])(
    'renders the %s temporal cache lifecycle without hiding operational facts',
    (status) => {
      render(<ProcurementOperationalTrace allocationView={{
        ...VIEW,
        temporal_cache_lifecycle: [{
          cache_key: 'procurement-summary:case-123', status,
          source_version: 'lane-18', evidence_cutoff: '2026-08-03T11:00:00Z',
          rebuild_status: status === 'rebuilding' ? 'running' : undefined,
        }],
      }} />);
      const cache = screen.getByTestId('proc-temporal-cache');
      expect(cache).toHaveTextContent(status.replace(/_/g, ' '));
      expect(cache).toHaveTextContent('Operational allocation facts: authoritative live read');
      expect(cache).toHaveTextContent(
        status === 'rebuilt' ? 'Generated narration: available' : 'Generated narration: unavailable',
      );
    },
  );

  it('projects disruption provenance into Evidence & Risk without overclaiming exposure', () => {
    render(<DisruptionEvidenceTrace allocationView={{ disruption_impacts: [{
      observation_id: 'obs-3', authority: 'proposal_only', status: 'bounded_recalculation_proposed',
      evidence: {
        source_id: 'ABF-ICS', source_revision: 'notice-44', source_licence: 'official notice terms',
        evidence_ref: 'evidence:44', claim_status: 'supported',
      },
      dependency_path: { edges: [
        { from_node_id: 'facility:shanghai', to_node_id: 'lane:cn-syd' },
      ] },
    }] }} />);
    const surface = screen.getByTestId('disruption-evidence-trace');
    expect(surface).toHaveTextContent('ABF-ICS · revision notice-44');
    expect(surface).toHaveTextContent('Claim: supported · authority proposal only');
    expect(surface).toHaveTextContent('Verified tenant exposure: facility:shanghai → lane:cn-syd');
    expect(surface).toHaveTextContent('Licence: official notice terms');
  });

  it('projects the invalidation and rebuild identity into Advanced technical details', () => {
    render(<TemporalCacheTechnicalTrace allocationView={{ temporal_cache_lifecycle: [{
      cache_key: 'procurement-summary:case-123', status: 'rebuilding', source_version: 'lane-19',
      evidence_cutoff: '2026-08-03T12:00:00Z', rebuild_status: 'running', rebuild_job_id: 'job-7',
    }] }} />);
    const surface = screen.getByTestId('temporal-cache-technical-trace');
    expect(surface).toHaveTextContent('State: rebuilding');
    expect(surface).toHaveTextContent('Source version: lane-19');
    expect(surface).toHaveTextContent('Rebuild: running · job-7');
    expect(surface).toHaveTextContent('Stale generated content served: no');
  });
});
