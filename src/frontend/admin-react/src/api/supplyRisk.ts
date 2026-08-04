import { http } from './client';

export type SupplyRiskScenario = {
  scenario_id: string;
  description: string;
  target_node_id: string;
  pestel_domains: string[];
  authority: 'simulation_only';
};

export type SupplyRiskWorkbench = {
  tenant_id: string;
  scenario: { scenario_id: string; parameter_hash: string; authority: string };
  target_node_id: string;
  authority: string;
  execution_allowed: boolean;
  pestel_domains: string[];
  signals: Array<{
    id: string;
    signal_type: string;
    direction: string;
    confidence: number;
    provenance_chain: string[];
    freshness: { available_at: string; age_days: number; status: string };
    official_source_candidates: Array<{
      source_id: string;
      publisher: string;
      trust_tier: string;
      licence_id: string;
      licence_url: string;
      measurement_scope: string;
      pestel_domains: string[];
      refresh_expectation?: string;
      decision_authority: string;
    }>;
  }>;
  dependency_paths: Array<{
    signal_id: string;
    signal_type: string;
    edge_ids: string[];
    node_path: string[];
    estimated_landed_cost_change_pct: { low: number; high: number };
    confidence: number;
  }>;
  impact: null | {
    landed_cost_change_pct: { low: number; high: number };
    availability_direction: string;
    magnitude_status: string;
  };
  confidence: number | null;
  causal_language: string | null;
  alternatives: string[];
  completeness: Record<string, any>;
  contradictions: {
    status: string;
    comparable_scope_count: number;
    incomparable_scopes: any[];
    winner: null;
    policy: string;
  };
  procurement_options: {
    status: string;
    authority: string;
    execution_allowed: boolean;
    human_approval_required: boolean;
    options: Array<{
      action_type: string;
      tradeoffs: string[];
      requires_human_approval: boolean;
    }>;
  };
  acceptance: Record<string, any>;
  shadow_evaluation: Record<string, any>;
};

export type CausalCohortEvaluation = {
  manifest: {
    version: string;
    scenarios: string[];
    seeds: number[];
    days: number;
    parameter_hash: string;
    run_count: number;
  };
  conditional_interval_coverage: Record<string, Record<string, {
    status: string;
    runs: number;
    evaluation_origins: number;
    nominal_coverage: number;
    empirical_coverage: number | null;
  }>>;
  policy_counterfactuals: {
    status: string;
    runs: number;
    observed_runs: number;
    metrics: Record<string, {
      status: string;
      baseline_mean: number | null;
      candidate_mean: number | null;
      delta_mean: number | null;
    }>;
    limitations: string[];
  };
  adversarial_evaluation: {
    enabled: boolean;
    misleading_correlation_records: number;
    contradictory_supplier_records: number;
    can_increase_autonomy: false;
  };
  authority: 'simulation_only';
  execution_allowed: false;
  causal_claim_allowed: false;
  can_increase_autonomy: false;
};

export const supplyRiskScenarios = () =>
  http<{ tenant_id: string; scenarios: SupplyRiskScenario[]; authority: string }>(
    '/api/v1/supply-risk/scenarios',
  );

export const supplyRiskWorkbench = (scenarioId: string, seed = 42, days = 400) =>
  http<SupplyRiskWorkbench>(
    `/api/v1/supply-risk/workbench/${encodeURIComponent(scenarioId)}?seed=${seed}&days=${days}`,
    { timeoutMs: 60_000 },
  );

export const evaluateCausalCohorts = (
  scenarioIds: string[],
  seeds: number[],
  days = 220,
) =>
  http<CausalCohortEvaluation>(
    '/api/v1/supply-risk/evaluation/cohorts',
    {
      method: 'POST',
      body: JSON.stringify({
        scenario_ids: scenarioIds,
        seeds,
        days,
        include_adversarial: true,
      }),
      timeoutMs: 120_000,
    },
  );
