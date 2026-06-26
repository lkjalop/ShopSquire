// Fulfilment / procurement API (operator control room). Each call maps to one backend transition;
// the workflow enforces the actor + the two gates. Independently testable/mockable via './client'.
import { http } from './client';

export interface FulfillmentCaseRow {
  case_id: string; buyer_uid_hash?: string | null; status: string;
  requested_by?: string | null; source_trace_id?: string | null; updated_at?: string | null;
}
export interface FulfillmentCaseView {
  case_id: string; state: string; state_json: Record<string, any>; source_trace_id?: string | null;
}
export interface JourneyEvent {
  state: string; event: string; actor_type: string; actor_id: string;
  reason_code?: string; evidence?: any; valid_from?: string; valid_to?: string | null;
}
// OPERATOR-only deal economics (margin / buyer-discount headroom / profit). Never buyer-facing.
export interface DealEconomics {
  quantity: number; supplier_unit_cost_cents: number; retail_unit_cents: number;
  supplier_cost_cents: number; retail_cents: number; gross_profit_cents: number; margin_pct: number;
  floor_margin_pct: number; max_buyer_discount_cents: number; max_buyer_discount_pct: number;
  profit_after_max_discount_cents: number; clears_floor: boolean;
}

const _fc = (id: string) => `/api/v1/fulfillment/cases/${encodeURIComponent(id)}`;
const _fcPost = (path: string, body?: any) =>
  http<FulfillmentCaseView>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });

export const listFulfillmentCases = () =>
  http<{ cases: FulfillmentCaseRow[] }>(`/api/v1/fulfillment/cases`).then((d) => d.cases || []);
export const getFulfillmentCaseOp = (id: string) => http<FulfillmentCaseView>(_fc(id));
export const getFulfillmentJourney = (id: string) =>
  http<{ journey: JourneyEvent[] }>(`${_fc(id)}/journey`).then((d) => d.journey || []);
export const fcDraftQuote = (id: string, item_ref: string, quantity: number, estimated_value_cents = 0) =>
  _fcPost(`${_fc(id)}/draft-quote`, { item_ref, quantity, estimated_value_cents });
export const fcRequestApproval = (id: string) =>
  http<FulfillmentCaseView & { approval_id?: string }>(`${_fc(id)}/request-approval`, { method: 'POST' });
export const fcDispatch = (id: string, content_hash: string) => _fcPost(`${_fc(id)}/dispatch`, { content_hash });
// HUMAN edits the pending draft before approving — re-hashes (voids prior approval), claim-safety enforced.
export const fcEditDraft = (id: string, subject: string, body: string) =>
  _fcPost(`${_fc(id)}/edit-draft`, { subject, body });
// bitemporal time-travel: the case as it was at instant `t`.
export const fcCaseAsOf = (id: string, t: string) =>
  http<{ case_id: string; as_of: string; state: string; state_json: Record<string, any> }>(
    `${_fc(id)}/as-of?t=${encodeURIComponent(t)}`);
export const fcDemoReply = (id: string, scenario: string, requested_qty: number) =>
  _fcPost(`${_fc(id)}/demo-reply`, { scenario, requested_qty });
export const fcValidateQuote = (id: string) => _fcPost(`${_fc(id)}/validate-quote`);
export const fcGenerateOptions = (id: string, body?: any) => _fcPost(`${_fc(id)}/options`, body || {});
// PO finalization — agent proposes, human approves+creates (idempotent, SANDBOX), then completes.
export const fcProposePO = (id: string) => _fcPost(`${_fc(id)}/propose-po`);
export const fcExecutePO = (id: string, idempotency_key?: string) =>
  _fcPost(`${_fc(id)}/execute-po`, { idempotency_key });
export const fcCompleteCase = (id: string) => _fcPost(`${_fc(id)}/complete`);
export const fcEconomics = (id: string) =>
  http<{ case_id: string; economics: DealEconomics | Record<string, never> }>(`${_fc(id)}/economics`)
    .then((d) => d.economics);
