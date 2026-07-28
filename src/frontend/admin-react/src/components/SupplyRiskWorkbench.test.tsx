import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SupplyRiskWorkbench } from './SupplyRiskWorkbench';
import { supplyRiskScenarios, supplyRiskWorkbench } from '../api';

vi.mock('../api', () => ({
  supplyRiskScenarios: vi.fn(),
  supplyRiskWorkbench: vi.fn(),
}));

describe('SupplyRiskWorkbench', () => {
  beforeEach(() => {
    vi.mocked(supplyRiskScenarios).mockResolvedValue({
      tenant_id: 'tenant-a',
      authority: 'simulation_only',
      scenarios: [{
        scenario_id: 'electronics_memory_allocation',
        description: 'Memory constraint',
        target_node_id: 'variant:a',
        pestel_domains: ['economic', 'technological'],
        authority: 'simulation_only',
      }],
    });
    vi.mocked(supplyRiskWorkbench).mockResolvedValue({
      tenant_id: 'tenant-a',
      scenario: { scenario_id: 'electronics_memory_allocation', parameter_hash: 'abc', authority: 'simulation_only' },
      target_node_id: 'variant:a',
      authority: 'simulation_only',
      execution_allowed: false,
      pestel_domains: ['economic', 'technological'],
      signals: [{
        id: 'signal:1',
        signal_type: 'capacity_constraint',
        direction: 'up',
        confidence: 0.8,
        provenance_chain: ['synthetic/source'],
        freshness: { available_at: '2026-07-01T00:00:00Z', age_days: 28, status: 'simulated' },
        official_source_candidates: [],
      }],
      dependency_paths: [{
        signal_id: 'signal:1',
        signal_type: 'capacity_constraint',
        edge_ids: ['edge:1'],
        node_path: ['component:a', 'variant:a'],
        estimated_landed_cost_change_pct: { low: 1, high: 3 },
        confidence: 0.8,
      }],
      impact: {
        landed_cost_change_pct: { low: 1, high: 3 },
        availability_direction: 'down',
        magnitude_status: 'bounded_estimate',
      },
      confidence: 0.8,
      causal_language: 'consistent_with',
      alternatives: ['foreign_exchange_movement'],
      completeness: {
        dependency_path: true,
        signal_provenance: true,
        official_source_candidates: false,
        missing_evidence: ['supplier_confirmation'],
      },
      contradictions: {
        status: 'no_conflict_single_observation',
        comparable_scope_count: 1,
        incomparable_scopes: [],
        winner: null,
        policy: 'never collapse different scope',
      },
      procurement_options: {
        status: 'human_review_required',
        authority: 'proposal_only',
        execution_allowed: false,
        human_approval_required: true,
        options: [{
          action_type: 'request_supplier_confirmation',
          tradeoffs: ['adds latency'],
          requires_human_approval: true,
        }],
      },
      acceptance: {},
      shadow_evaluation: {},
    });
  });

  it('shows evidence, uncertainty and prohibited execution', async () => {
    render(<SupplyRiskWorkbench />);
    const labels = await screen.findByTestId('supply-risk-trust-labels');
    expect(labels).toHaveTextContent('SIMULATION ONLY');
    expect(labels).toHaveTextContent('PROHIBITED');
    expect(labels).toHaveTextContent('economic, technological');
    expect(screen.getByText(/component:a → variant:a/)).toBeInTheDocument();
    expect(screen.getByText(/Official source adapter: missing/)).toBeInTheDocument();
    expect(screen.getByText(/human approval required/)).toBeInTheDocument();
  });
});
