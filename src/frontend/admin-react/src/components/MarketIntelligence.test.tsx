import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MarketIntelligence } from './MarketIntelligence';
import {
  experimentState,
  fetchExecutiveMetrics,
  governancePulse,
  replayState,
  searchDemandAuthority,
  supportResponse,
} from '../api';

vi.mock('../api', () => ({
  experimentEvaluate: vi.fn(),
  experimentPromote: vi.fn(),
  experimentRevert: vi.fn(),
  experimentState: vi.fn(),
  fetchExecutiveMetrics: vi.fn(),
  governancePulse: vi.fn(),
  marketDigest: vi.fn(),
  marketState: vi.fn(),
  refreshMarket: vi.fn(),
  replayAdvance: vi.fn(),
  replayReset: vi.fn(),
  replayState: vi.fn(),
  searchDemandAuthority: vi.fn(),
  supportResponse: vi.fn(),
}));

describe('MarketIntelligence trust labels', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(replayState).mockResolvedValue({
      signals: 3,
      active_findings: 1,
      findings: [],
      label: 'SYNTHETIC REPLAY',
      series: {
        demand: [10, 12],
        conversion: [8, 7],
        dates: ['2026-07-27', '2026-07-28'],
      },
    });
    vi.mocked(experimentState).mockResolvedValue({
      experiment_id: 'ranking',
      status: 'reverted',
      live: false,
      assignments: {},
      last_decision: null,
      last_uplift_pct: null,
      adaptation_killed: false,
    });
    vi.mocked(fetchExecutiveMetrics).mockResolvedValue({
      tenant_id: 'replay-demo',
      data_quality: { event_count: 2 },
      estimates: {},
      actions: [],
      metrics: [{
        metric: 'weeks_of_supply',
        tenant_id: 'replay-demo',
        subject_type: 'sku',
        subject_id: 'SKU-1',
        value: 2,
        unit: 'weeks',
        as_of: '2026-07-28T00:00:00Z',
        status: 'simulated',
        confidence: 0.6,
        coverage: 0.8,
        source_count: 2,
        source_records: [],
        provenance_chain: ['synthetic-replay'],
        definition_version: 'v1',
        visibility: 'operator',
        metadata: {},
      }],
    });
    vi.mocked(governancePulse).mockRejectedValue(new Error('not configured'));
    vi.mocked(supportResponse).mockRejectedValue(new Error('not configured'));
    vi.mocked(searchDemandAuthority).mockResolvedValue({
      tenant_id: 'replay-demo', search_interest_count: 1, qualified_searches: 1,
      unresolved_concept_count: 0, unresolved_concept_rate: 0,
      no_qualified_match_count: 0, no_qualified_match_rate: 0,
      provisional_cart_count: 0, committed_case_count: 0, ordered_case_count: 0,
      fulfilled_case_count: 0, qualified_to_cart_rate: null, cart_to_commitment_rate: null,
      qualified_interest_units: 30, committed_demand_units: 0, confirmed_atp_units: 0,
      transferable_units: 0, qualified_unmet_units: 0, supplier_enquiry_pressure_units: 0,
      inventory_source_versions: [], inventory_freshness_states: [],
      eligible_forecast_signal_count: 1, forecast_influence: 'shadow_only',
      forecast_comparison_status: 'insufficient_sealed_outcomes', projected_revenue: null,
      projected_revenue_status: 'undefined_without_order_or_approved_value_basis',
      inventory_action_allowed: false, authority_note: 'search is interest', simulation_only: true,
      observation_authority: 'simulation',
      as_of: '2026-08-05T00:00:00Z',
    });
  });

  it('shows synthetic, shadow and freshness labels and separates coverage from confidence', async () => {
    render(<MarketIntelligence />);

    const labels = await screen.findByTestId('mi-trust-labels');
    expect(labels).toHaveTextContent('Evidence: SYNTHETIC');
    expect(labels).toHaveTextContent('Adaptation authority: SHADOW / NOT LIVE');
    expect(labels).toHaveTextContent('Freshness: data through 2026-07-28');
    expect(await screen.findByText(/80% coverage/)).toHaveTextContent('60% confidence');
    expect(screen.getByText('simulated')).toBeInTheDocument();
    const authority = await screen.findByTestId('search-demand-authority');
    expect(authority).toHaveTextContent('Qualified interest30 units');
    expect(authority).toHaveTextContent('Committed demand0 units');
    expect(authority).toHaveTextContent('Projected revenue: undefined');
    expect(authority).toHaveTextContent('Forecast influence: shadow only');
    expect(authority).toHaveTextContent('Inventory action: not allowed');
  });
});
