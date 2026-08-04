import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fcDecisionIntelligence } from '../../api/fulfillment';
import DecisionIntelligence from './DecisionIntelligence';

vi.mock('../../api/fulfillment', () => ({ fcDecisionIntelligence: vi.fn() }));

describe('DecisionIntelligence', () => {
  beforeEach(() => vi.resetAllMocks());

  it('renders missing evidence as undefined rather than zero', async () => {
    vi.mocked(fcDecisionIntelligence).mockResolvedValue({
      status: 'not_materialized', context: null, proposal: null, comparison: null,
    });
    render(<DecisionIntelligence caseId="case-1" />);
    expect(await screen.findByTestId('decision-not-materialized')).toHaveTextContent('undefined—not zero');
  });

  it('surfaces exact inputs and preserves both human gates', async () => {
    vi.mocked(fcDecisionIntelligence).mockResolvedValue({
      status: 'available',
      context: {
        snapshot_id: 'snapshot',
        case_version_id: 'version-1234567890',
        facts_hash: 'hash-1234567890',
        source_authority: 'simulation',
        facts: {
          demand: { mean_daily: 4, variance_daily: 2 },
          supplier_lead_time: { mean_days: 10 },
          inventory: { current_atp: 15, incoming_supply: 5 },
          service_level: 0.95,
        },
        provenance: { forecast: 'eval-1' },
        created_by: 'operator-1',
        created_at: '2026-07-28T00:00:00Z',
        immutable: true,
      },
      proposal: {
        proposal_id: 'proposal',
        status: 'simulation_only',
        blocked_reasons: ['non_authoritative_inputs'],
        authority: 'proposal_only',
        result: {
          safety_stock_units: 6.2, reorder_point_units: 46.2,
          suggested_order_units: 30, moq_units: 20, pack_size_units: 10,
        },
        created_at: '2026-07-28T00:00:00Z',
      },
      comparison: {
        comparison_id: 'comparison',
        status: 'observed',
        authority: 'comparison_only',
        ranked: [{ quote_id: 'supplier-b', comparable_landed_unit_minor: '950.0000', currency: 'AUD', uom: 'each' }],
        recommended: { quote_id: 'supplier-b', comparable_landed_unit_minor: '950.0000', currency: 'AUD', uom: 'each' },
        excluded: [{ quote_id: 'supplier-a', reason: 'fx_authority_required' }],
        can_authorize_purchase: false,
        created_at: '2026-07-28T00:00:00Z',
      },
    });
    render(<DecisionIntelligence caseId="case-1" />);
    expect(await screen.findByTestId('decision-exact-inputs')).toHaveTextContent('Demand 4/day');
    expect(screen.getByTestId('replenishment-proposal')).toHaveTextContent('proposal only');
    expect(screen.getByTestId('replenishment-proposal')).toHaveTextContent('non authoritative inputs');
    expect(screen.getByTestId('landed-cost-comparison')).toHaveTextContent('cannot authorize purchase');
    expect(screen.getByTestId('landed-cost-comparison')).toHaveTextContent('1 comparable · 1 excluded');
  });
});
