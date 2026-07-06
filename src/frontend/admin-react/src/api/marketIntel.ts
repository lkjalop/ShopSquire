// Market-intelligence API (operator). Drives the REAL M3 path (ingestion → analysis → findings) via
// the SYNTHETIC replay endpoints. Independently testable/mockable via './client'.
import { http } from './client';

export interface ReplayFinding {
  type: string; severity: string; summary: string; entity_ref?: string | null;
}
export interface ReplayState {
  signals: number; active_findings: number; findings: ReplayFinding[];
  series?: { demand: number[]; conversion: number[]; dates: string[] }; label?: string;
}

export const replayState = () => http<ReplayState>(`/api/v1/fulfillment/replay/state`);
export const replayReset = () => http<any>(`/api/v1/fulfillment/replay/reset`, { method: 'POST' });
export const replayAdvance = (day: number) =>
  http<{ state: ReplayState }>(`/api/v1/fulfillment/replay/advance?day=${day}`, { method: 'POST' });

// REAL pipeline (default tenant) — live ingestion → analysis → findings, the counterpart to replay.
export const marketState = () => http<ReplayState>(`/api/v1/fulfillment/market/state`);
export const refreshMarket = () =>
  http<{ refreshed: any; state: ReplayState }>(`/api/v1/fulfillment/market/refresh`, { method: 'POST' });

// Ranking-experiment console — promote/observe/evaluate/revert the live-adaptation loop (operator levers).
export interface ExperimentState {
  experiment_id: string; status: string; live: boolean;
  assignments: Record<string, number>;
  last_decision: string | null; last_uplift_pct: number | null; adaptation_killed: boolean;
}
const _exp = '/api/v1/fulfillment/market/experiment';
export const experimentState = () => http<ExperimentState>(`${_exp}/state`);
export const experimentPromote = () => http<ExperimentState>(`${_exp}/promote`, { method: 'POST', body: '{}' });
export const experimentRevert = () => http<ExperimentState>(`${_exp}/revert`, { method: 'POST', body: '{}' });
// default 30 samples/arm — evaluating on 1 sample yields se=0 → fake "significance" → scale/auto-revert on noise.
export const experimentEvaluate = (min_samples = 30) =>
  http<any>(`${_exp}/evaluate`, { method: 'POST', body: JSON.stringify({ min_samples }) });

// Market digest (deck M3 summarization) — the operator's brief from ACTIVE findings. Deterministic
// facts always; the flag-gated local-LLM only rewrites the narrative wording. Advisory-only.
export interface MarketDigest {
  mode: 'deterministic' | 'llm_rewrite';
  finding_count: number;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
  top_findings: Array<{ finding_type: string; severity: string; entity_ref?: string | null;
                        confidence?: number; summary?: string | null }>;
  suggested_focus: string[];
  narrative: string;
  advisory_only: boolean;
}
export const marketDigest = () => http<MarketDigest>(`/api/v1/fulfillment/market/digest`);

// M5 SUPPORT lane — the pre-sales phrasing angle to counter the dominant buyer objection (deck: price
// objections → shift to lifetime VALUE). Operator-only; recommends an APPROVED angle, never free-form copy.
export interface SupportResponse {
  objection_theme?: string; response_angle?: string; guidance?: string; source?: string;
}
export const supportResponse = (objection?: string) =>
  http<SupportResponse>(
    `/api/v1/fulfillment/market/support-response${objection ? `?objection=${encodeURIComponent(objection)}` : ''}`,
  );

// Governance pulse — the owner/governance Step-11 visibility snapshot (read-only, writes nothing).
export interface GovernancePulse {
  tenant_id: string;
  signal_decision_state: {
    active_findings: number;
    findings_by_severity: Record<string, number>;
    ai_confidence_distribution: Record<string, number>;
    adaptation_mode: { kill_switch: boolean; hippograph_mode: string; experiment_live: boolean };
  };
  experiment_health: {
    status: string; live: boolean; outcomes_recorded: number; scope?: string;
    decision_breakdown: Record<string, number>; rollback_count: number;
    last_decision: string | null; last_uplift_pct: number | null;
  };
  policy_compliance: {
    actions_evaluated: number; actions_blocked: number; policy_block_rate: number;
    block_reasons: Record<string, number>;
    contacts_evaluated: number; contacts_suppressed: number; contact_suppression_rate: number;
    suppression_by_region: Record<string, number>; exception_count: number;
  };
  operational_pressure: {
    findings_by_type: Record<string, number>; critical_findings: number;
    total_signal_findings: number; open_action_proposals: number;
  };
}
// tenant_id lets the pulse follow the view — the isolated 'replay-demo' tenant during synthetic replay,
// else the real 'default' operational tenant.
export const governancePulse = (tenantId = 'default') =>
  http<GovernancePulse>(`/api/v1/fulfillment/governance/pulse?tenant_id=${encodeURIComponent(tenantId)}`);
