// Decision-trace API (operator). Bitemporal decision query + per-trace events/causal graph + the
// approve/reject/reopen lifecycle. Independently testable/mockable via './client'.
import { http } from './client';

export type DecisionRow = {
  id: string;
  agent_name: string;
  valid_from?: string;
  valid_to?: string | null;
  system_from?: string;
  system_to?: string | null;
  input_data?: any;
  proposed_action?: any;
  policy_version?: string;
  approval_required?: boolean;
  execution_status?: string;
};

export type DecisionTraceEvent = {
  id: string;
  seq?: number | null;
  trace_id?: string;
  event_type?: string;
  source_type?: string | null;
  source_id?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  payload?: any;
  created_at?: string;
};

export type DecisionTraceQuery = {
  decision_id: string;
  timestamp?: string;
  input_query?: string | null;
  intent_analysis?: any;
  agent_chain?: any[];
  rag_context?: any;
  evidence?: any;
  recommendation?: any;
  policy_gates?: any;
  bitemporal?: any;
  model_selection?: any;
  events?: DecisionTraceEvent[];
};

export type DecisionCausalGraph = {
  trace_id: string;
  nodes: Array<{
    id: string;
    event_type?: string;
    source_type?: string;
    source_id?: string;
    target_type?: string;
    target_id?: string;
    created_at?: string;
  }>;
  edges: Array<{ from: string; to: string; type?: string }>;
};

export async function fetchDecisions(): Promise<DecisionRow[]> {
  const data = await http<{ results: DecisionRow[] }>(`/api/v1/decisions/query`);
  return data.results || [];
}

export async function fetchDecisionsFiltered(params: { agent?: string }): Promise<DecisionRow[]> {
  const q = new URLSearchParams();
  if (params.agent) q.set('agent_name', params.agent);
  const data = await http<{ results: DecisionRow[] }>(`/api/v1/decisions/query?${q.toString()}`);
  return data.results || [];
}

export async function fetchDecisionTraceQuery(traceId: string): Promise<DecisionTraceQuery> {
  return http(`/api/v1/decisions/${encodeURIComponent(traceId)}/query?include_events=true`);
}

export async function fetchDecisionSession(sessionId: string): Promise<{ session_id: string; count: number; decisions: any[] }> {
  return http(`/api/v1/decisions/session/${encodeURIComponent(sessionId)}`);
}

export async function fetchDecisionCausal(traceId: string): Promise<DecisionCausalGraph> {
  return http(`/api/v1/decisions/trace/${encodeURIComponent(traceId)}/causal`);
}

export async function fetchInterleavingSummary(traceId: string): Promise<{ summary: any }> {
  return http(`/api/v1/admin/interleaving/${encodeURIComponent(traceId)}/summary`);
}

export async function approveDecision(decisionId: string, approvedBy: string): Promise<void> {
  await http(`/api/v1/decisions/${encodeURIComponent(decisionId)}/approve?approved_by=${encodeURIComponent(approvedBy)}`, { method: 'POST' });
}

export async function rejectDecision(decisionId: string, rejectedBy: string, reason?: string): Promise<void> {
  const q = new URLSearchParams();
  q.set('rejected_by', rejectedBy);
  if (reason) q.set('reason', reason);
  await http(`/api/v1/decisions/${encodeURIComponent(decisionId)}/reject?${q.toString()}`, { method: 'POST' });
}

export async function reopenDecision(decisionId: string, actor: string, comment?: string): Promise<void> {
  const q = new URLSearchParams();
  q.set('actor', actor);
  if (comment) q.set('comment', comment);
  await http(`/api/v1/decisions/${encodeURIComponent(decisionId)}/reopen?${q.toString()}`, { method: 'POST' });
}
