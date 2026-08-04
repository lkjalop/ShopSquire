import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SupplyRiskWorkbench } from './SupplyRiskWorkbench';
import { evaluateCausalCohorts, supplyRiskScenarios, supplyRiskWorkbench } from '../api';

vi.mock('../api', () => ({
  supplyRiskScenarios: vi.fn(),
  supplyRiskWorkbench: vi.fn(),
  evaluateCausalCohorts: vi.fn(),
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
    vi.mocked(evaluateCausalCohorts).mockResolvedValue({
      manifest: {
        version: 'cohort-v1',
        scenarios: ['electronics_memory_allocation'],
        seeds: [7, 13, 29],
        days: 220,
        parameter_hash: 'abcdef1234567890',
        run_count: 3,
      },
      conditional_interval_coverage: {},
      policy_counterfactuals: {
        status: 'observed',
        runs: 3,
        observed_runs: 3,
        metrics: {
          fill_rate: {
            status: 'observed',
            baseline_mean: 0.8,
            candidate_mean: 0.9,
            delta_mean: 0.1,
          },
          waste_units: {
            status: 'undefined_no_ageing_model',
            baseline_mean: null,
            candidate_mean: null,
            delta_mean: null,
          },
        },
        limitations: ['means can hide tail outcomes'],
      },
      adversarial_evaluation: {
        enabled: true,
        misleading_correlation_records: 3,
        contradictory_supplier_records: 3,
        can_increase_autonomy: false,
      },
      authority: 'simulation_only',
      execution_allowed: false,
      causal_claim_allowed: false,
      can_increase_autonomy: false,
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

  it('runs a bounded multi-seed proof without granting causal or autonomous authority', async () => {
    render(<SupplyRiskWorkbench />);
    await screen.findByTestId('supply-risk-trust-labels');

    fireEvent.click(screen.getByRole('button', { name: /Evaluate seeds/ }));

    const evaluation = await screen.findByTestId('causal-cohort-evaluation');
    expect(evaluateCausalCohorts).toHaveBeenCalledWith(
      ['electronics_memory_allocation'],
      [7, 13, 29],
      220,
    );
    expect(evaluation).toHaveTextContent('Runs: 3');
    expect(evaluation).toHaveTextContent('Causal claim: prohibited');
    expect(evaluation).toHaveTextContent('Autonomy increase: prohibited');
    expect(evaluation).toHaveTextContent('Misleading correlations: 3');
  });
});
