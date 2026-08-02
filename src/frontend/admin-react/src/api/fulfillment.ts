// Fulfilment / procurement API (operator control room). Each call maps to one backend transition;
// the workflow enforces the actor + the two gates. Independently testable/mockable via './client'.
import { http } from './client';

export interface FulfillmentCaseRow {
  case_id: string; buyer_uid_hash?: string | null; status: string;
  requested_by?: string | null; source_trace_id?: string | null; updated_at?: string | null;
  item_ref?: string | null; quantity?: number | null;
}
// M4 demand→sales decision overlay (from sales_response_policy.decide) — attached to margin advice so the
// operator sees the demand-aware call (discount/reorder pressure) alongside the margin headroom. Optional:
// present only when the sales-response overlay is enabled server-side.
export interface SalesResponse {
  discount_action: 'increase' | 'reduce' | 'hold' | string;
  recommended_discount_pct?: number;
  price_bias?: string; promotion_bias?: string; reorder_urgency?: string; messaging_emphasis?: string;
  rationale?: string[];
  situation?: { demand_trend?: string; inventory_position?: string; margin_headroom?: string };
}
export interface MarginAdvice {
  available: boolean; verdict: 'healthy' | 'thin' | 'below_floor' | null;
  economics?: Record<string, any>; max_buyer_discount_cents?: number;
  recommended_buyer_discount_cents?: number; supplier_last_invoice_cents?: number | null;
  rationale?: string[];
  sales_response?: SalesResponse;
}
export interface FulfillmentCaseView {
  case_id: string; state: string; state_json: Record<string, any>; source_trace_id?: string | null;
  margin_advice?: MarginAdvice;
  margin_warning?: { mode: string; message: string };
  email_enrichment?: { status: string; attempts: number; error?: string | null };
  quarantine_dispositions?: Array<{
    action: string; actor_id: string; note?: string | null;
    fresh_case_id?: string | null; created_at?: string | null;
  }>;
}
export interface JourneyEvent {
  state: string; event: string; actor_type: string; actor_id: string;
  reason_code?: string; evidence?: any; valid_from?: string; valid_to?: string | null;
}
export interface CommunicationEvent {
  event_id: string; observation_id: string; state: string; actor_type: string;
  actor_id?: string; reason?: string; grounding_refs?: string[];
  commercial_effect?: 'prevented' | 'none' | string; occurred_at?: string;
}
export interface FulfillmentJourneyView {
  journey: JourneyEvent[];
  communications: CommunicationEvent[];
  communication_status: string;
}

export interface AllocationWorkbenchView {
  tenant_id: string;
  sku?: string | null;
  authority: string;
  execution_authority: string;
  summary: {
    committed_quantity: number;
    allocated_quantity: number;
    shortfall_quantity: number;
    supplier_confirmed_quantity: number;
    supplier_unresolved_quantity: number;
    allocation_pressure: number;
    oldest_queue_age_seconds: number;
  };
  demands: Array<{
    demand_ref: string; case_ref: string; sku: string; destination_id: string; stage: string;
    requested_quantity: number; allocated_quantity: number; shortfall_quantity: number;
    priority_tier: number; queue_age_seconds: number; promise_state?: string | null;
    alternatives_required: boolean;
  }>;
  sourcing_batches: Array<{
    batch_ref: string; sku: string; destination_id: string; status: string; quantity: number;
    window_ends_at: string; child_demand_count: number; fulfillment_case_id?: string | null;
  }>;
  sourcing_waves: Array<{
    wave_ref: string; supplier_id: string; supplier_facility_id: string; currency: string;
    incoterm: string; merchant_destination_id: string; status: string; window_ends_at: string;
    standalone_freight_cents: number; consolidated_freight_cents: number;
    handling_cents: number; estimated_savings_cents: number; batch_count: number;
    total_quantity: number;
  }>;
  route_proposals: Array<{
    proposal_ref: string; case_ref: string; mode: string; status: string;
    destination_token: string; eta_days: { min?: number | null; max?: number | null };
    components: Record<string, any>; state_prevented?: string | null;
    pii_release_authorized: boolean; created_at: string;
    privacy: { status: string; jurisdiction?: string | null; purpose?: string | null;
               retention_until?: string | null };
  }>;
  privacy: { buyer_identities_exposed: boolean; child_demands_anonymized: boolean };
}
// OPERATOR-only deal economics (margin / buyer-discount headroom / profit). Never buyer-facing.
export interface DealEconomics {
  quantity: number; supplier_unit_cost_cents: number; retail_unit_cents: number;
  supplier_cost_cents: number; retail_cents: number; gross_profit_cents: number; margin_pct: number;
  floor_margin_pct: number; max_buyer_discount_cents: number; max_buyer_discount_pct: number;
  profit_after_max_discount_cents: number; clears_floor: boolean;
}

export interface ForecastModelEvidence {
  status: string;
  daily_units?: number | null;
  horizon_units?: number | null;
  wape?: number | null;
  wape_status?: string;
  mase?: number | null;
  mase_status?: string;
  bias?: number | null;
  origins?: number;
}

export interface InventoryForecastIntelligence {
  sku: string;
  status: string;
  selected_model?: string | null;
  history_points: number;
  origins: number;
  horizon: { kind: string; days: number; input_days: number };
  models: Record<string, ForecastModelEvidence>;
  segmentation: {
    abc_class?: string;
    abc_status?: string;
    xyz_class?: string;
    xyz_status?: string;
    coefficient_of_variation?: number | null;
  };
  source: {
    kind: string;
    status: string;
    watermark?: string | null;
    sources?: string[];
    row_count?: number;
    lookback_days?: number;
  };
  authority: 'shadow_evaluation_only' | string;
  can_increase_autonomy: boolean;
  materialized: boolean;
  evaluation_id?: string;
  computation_version: string;
}

export interface ProcurementDecisionIntelligence {
  status: 'available' | 'not_materialized' | string;
  context: null | {
    snapshot_id: string;
    case_version_id: string;
    facts_hash: string;
    source_authority: 'authoritative' | 'simulation' | string;
    facts: Record<string, any>;
    provenance: Record<string, any>;
    created_by: string;
    created_at: string;
    immutable: boolean;
  };
  proposal: null | {
    proposal_id: string;
    status: string;
    blocked_reasons: string[];
    authority: 'proposal_only' | string;
    result: Record<string, any>;
    created_at: string;
  };
  comparison: null | {
    comparison_id: string;
    status: string;
    authority: 'comparison_only' | string;
    ranked: Array<Record<string, any>>;
    recommended?: Record<string, any> | null;
    excluded: Array<{ quote_id: string; reason: string }>;
    can_authorize_purchase: boolean;
    created_at: string;
  };
}

const _fc = (id: string) => `/api/v1/fulfillment/cases/${encodeURIComponent(id)}`;
const _fcPost = (path: string, body?: any) =>
  http<FulfillmentCaseView>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });

export const listFulfillmentCases = () =>
  http<{ cases: FulfillmentCaseRow[] }>(`/api/v1/fulfillment/cases`).then((d) => d.cases || []);
export const fetchAllocationWorkbench = (sku?: string) =>
  http<AllocationWorkbenchView>(
    `/api/v1/admin/allocation/workbench${sku ? `?sku=${encodeURIComponent(sku)}` : ''}`,
  );
export const getFulfillmentCaseOp = (id: string) => http<FulfillmentCaseView>(`${_fc(id)}/operator-view`);
export const getFulfillmentJourney = (id: string) =>
  http<{ journey: JourneyEvent[] }>(`${_fc(id)}/journey`).then((d) => d.journey || []);
export const getFulfillmentJourneyView = (id: string) =>
  http<FulfillmentJourneyView>(`${_fc(id)}/journey`).then((data) => ({
    journey: data.journey || [],
    communications: data.communications || [],
    communication_status: data.communication_status || 'unavailable',
  }));
export const fcDraftQuote = (id: string, item_ref: string, quantity: number, estimated_value_cents = 0) =>
  _fcPost(`${_fc(id)}/draft-quote`, { item_ref, quantity, estimated_value_cents });
// Phase 3: buyer qualification (human verifies intent before supplier contact).
export interface QualificationRoom { ok?: boolean; incident_id?: string; buyer_token?: string; staff_token?: string; }
export const fcStartQualification = (id: string) =>
  http<FulfillmentCaseView & { qualification_room?: QualificationRoom }>(
    `${_fc(id)}/start-qualification`, { method: 'POST' });
export const fcQualify = (id: string, qualified: boolean, notes?: string) =>
  _fcPost(`${_fc(id)}/qualify`, { qualified, notes });
// WS-C/D: request-approval also reports the autonomous-send outcome (OFF/escalated/sent + reason).
export interface AutonomousSendOutcome { action: 'sent' | 'escalated' | 'send_failed'; reason: string; provider_ref?: string | null; }
export const fcRequestApproval = (id: string) =>
  http<FulfillmentCaseView & { approval_id?: string; autonomous_send?: AutonomousSendOutcome }>(
    `${_fc(id)}/request-approval`, { method: 'POST' });
// WS-D observability: the autonomous-RFQ-send decision trail + the live enabled/killed toggle state.
export interface AutonomousAuditRow {
  action_type: string; decision: 'allow' | 'escalate' | 'deny'; reason: string;
  confidence: number; subject?: string | null; target?: string | null; created_at?: string | null;
}
export interface TransportHealth { mode: 'sandbox' | 'smtp'; configured: boolean; missing: string[]; transmits: boolean; }
export interface AutonomousAudit {
  rows: AutonomousAuditRow[];
  summary: { sent: number; escalated: number; by_reason: Record<string, number> };
  enabled: boolean; killed: boolean; transport: TransportHealth;
}
export const fcAutonomousAudit = (limit = 100) =>
  http<AutonomousAudit>(`/api/v1/fulfillment/autonomous/audit?limit=${encodeURIComponent(String(limit))}`);

// Multi-line order → grouped cases (one per supplier). "15 laptops + 10 monitors + 5 headsets".
export interface OrderGroupCase {
  case_id: string; supplier_ref?: string | null; supplier_name?: string | null;
  recipient_domain?: string | null; lines: { item_ref: string; quantity: number }[]; total_quantity: number;
}
export interface FromOrderResult { order_group_id: string; case_count: number; cases: OrderGroupCase[]; plan?: any; }
export const fcFromOrder = (query: string) =>
  http<FromOrderResult>(`/api/v1/fulfillment/cases/from-order`, { method: 'POST', body: JSON.stringify({ query }) });
export const fcDispatch = (id: string, content_hash: string) => _fcPost(`${_fc(id)}/dispatch`, { content_hash });
export const fcQuarantineDisposition = (
  id: string,
  action: 'keep_quarantined' | 'discard' | 'open_fresh_rfq',
  note?: string,
) => _fcPost(`${_fc(id)}/quarantine-disposition`, { action, note });

// Operator notification feed — new cart confirmations, amendments/supersessions, supplier out-of-band events.
export interface ProcurementNotification {
  id: string; kind: string; summary: string; ref?: string | null; created_at?: string; seen?: boolean;
}
export const fcNotifications = (unseenOnly = false, limit = 50) =>
  http<{ notifications: ProcurementNotification[]; unseen: number }>(
    `/api/v1/fulfillment/notifications?unseen_only=${unseenOnly ? 'true' : 'false'}&limit=${limit}`);
export const fcMarkNotificationsSeen = (ids?: string[]) =>
  http<{ marked: number }>(`/api/v1/fulfillment/notifications/seen`,
    { method: 'POST', body: JSON.stringify(ids ? { ids } : {}) });
// Export the case as an OKF (Open Knowledge Format) document — a portable audit artifact.
export const fcCaseOkf = (id: string) =>
  http<{ case_id: string; type: string; filename: string; okf: string }>(`${_fc(id)}/okf`);
// Ranked, confidence-scored, provenance-tagged approved-supplier shortlist (read-only review prefill).
export interface SupplierCandidate {
  supplier_id: string; legal_name: string; contact_email?: string | null; domain: string;
  risk_tier: string; on_time_rate: number; reliability: number; lead_time_days?: number | null;
  rank_score?: number | null; prior_dealings: number; last_invoice_cents?: number | null;
  last_seen_at?: string | null; confidence: number; flags: string[]; recommended: boolean;
  provenance: Record<string, string>;
}
export const fcSupplierCandidates = (id: string) =>
  http<{ case_id: string; item_ref: string; candidates: SupplierCandidate[] }>(`${_fc(id)}/supplier-candidates`);
// Competitive RFQ fan-out (Phase 1): a caged draft preview per top-N approved supplier (never sends).
export interface RfqFanoutDraft {
  recipient_ref: string; recipient_domain: string; recipient_email?: string | null;
  subject: string; body: string; confidence: number; content_hash: string;
  send_gate: { decision?: string; reasons?: string[]; [k: string]: any };
}
export const fcRfqFanout = (id: string, topN = 3) =>
  http<{ case_id: string; item_ref: string; top_n: number; quantity: number; count: number; drafts: RfqFanoutDraft[] }>(
    `${_fc(id)}/rfq-fanout?top_n=${encodeURIComponent(String(topN))}`);
// Quote comparison: rank competing supplier quotes by a vertical-blind composite (price·lead·reliability).
export interface QuoteInput {
  supplier_ref?: string; recipient_domain?: string; unit_price_cents: number;
  lead_time_days?: number | null; reliability?: number | null; quantity?: number | null; valid_until?: string | null;
}
export interface RankedQuote extends QuoteInput {
  scores: { price: number; lead_time: number; reliability: number }; composite: number; reasons: string[];
}
export const fcCompareQuotes = (id: string, quotes: QuoteInput[], weights?: Record<string, number>) =>
  http<{ case_id: string; ranked: RankedQuote[]; recommended: RankedQuote | null; considered: number; excluded: number }>(
    `${_fc(id)}/compare-quotes`, { method: 'POST', body: JSON.stringify({ quotes, weights }) });
export const fcDecisionIntelligence = (id: string) =>
  http<ProcurementDecisionIntelligence>(`${_fc(id)}/decision-intelligence`);
export const fcCreateDecisionContext = (id: string, facts: Record<string, any>) =>
  http<any>(`${_fc(id)}/decision-context`, {
    method: 'POST',
    body: JSON.stringify({ facts }),
  });
export const fcCreateReplenishmentProposal = (id: string, contextSnapshotId: string) =>
  http<any>(`${_fc(id)}/replenishment-proposal`, {
    method: 'POST',
    body: JSON.stringify({ context_snapshot_id: contextSnapshotId }),
  });
export const fcCreateLandedCostComparison = (
  id: string,
  body: {
    context_snapshot_id: string;
    target_currency: string;
    target_uom: string;
    quotes: Array<Record<string, any>>;
    at_time?: string;
  },
) => http<any>(`${_fc(id)}/landed-cost-comparison`, {
  method: 'POST',
  body: JSON.stringify(body),
});
// RFI: HUMAN asks the resolved supplier a scoped clarification before approving the RFQ (claim-safe).
export const fcRequestInfo = (id: string, question: string) => _fcPost(`${_fc(id)}/request-info`, { question });
// record the supplier's RFI reply → back to the approval gate.
export const fcSupplierInfo = (id: string, answer: string) => _fcPost(`${_fc(id)}/supplier-info`, { answer });
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

export const fetchInventoryForecast = (sku: string, leadTimeDays = 14) =>
  http<InventoryForecastIntelligence>(
    `/api/v1/admin/bi/inventory-intelligence/${encodeURIComponent(sku)}/forecast`
    + `?lead_time_days=${encodeURIComponent(String(leadTimeDays))}`,
  );

export const materializeInventoryForecast = (sku: string, leadTimeDays = 14) =>
  http<InventoryForecastIntelligence>(
    `/api/v1/admin/bi/inventory-intelligence/${encodeURIComponent(sku)}/forecast`
    + `?lead_time_days=${encodeURIComponent(String(leadTimeDays))}`,
    { method: 'POST' },
  );
