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

export const supplyRiskScenarios = () =>
  http<{ tenant_id: string; scenarios: SupplyRiskScenario[]; authority: string }>(
    '/api/v1/supply-risk/scenarios',
  );

export const supplyRiskWorkbench = (scenarioId: string, seed = 42, days = 400) =>
  http<SupplyRiskWorkbench>(
    `/api/v1/supply-risk/workbench/${encodeURIComponent(scenarioId)}?seed=${seed}&days=${days}`,
    { timeoutMs: 60_000 },
  );
