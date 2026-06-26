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
export const experimentEvaluate = (min_samples = 1) =>
  http<any>(`${_exp}/evaluate`, { method: 'POST', body: JSON.stringify({ min_samples }) });
