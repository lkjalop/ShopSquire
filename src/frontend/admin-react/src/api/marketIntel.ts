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
