export type TraceProjectionEvent = {
  event_type?: string;
  payload?: Record<string, any>;
};

function originalEventType(event: TraceProjectionEvent): string {
  return String(
    event?.payload?._original_event_type
    || event?.payload?.original_event_type
    || event?.event_type
    || '',
  ).toLowerCase().trim();
}

export function resolveExecutionSteps(trace: any, events: TraceProjectionEvent[]): any[] {
  if (Array.isArray(trace?.execution_steps) && trace.execution_steps.length > 0) {
    return trace.execution_steps;
  }
  const persisted = [...(events || [])].reverse().find((event) => (
    Array.isArray(event?.payload?.execution_steps)
  ));
  return persisted?.payload?.execution_steps || [];
}

export function resolveRecommendationPayload(events: TraceProjectionEvent[]): any | null {
  const candidates = (events || []).flatMap((event) => {
    const payload = event?.payload || {};
    const original = originalEventType(event);
    if (original !== 'recommendation_result') return [];
    const rightPanel = payload?.right_panel_contract && typeof payload.right_panel_contract === 'object'
      ? payload.right_panel_contract
      : (payload?.right_panel && typeof payload.right_panel === 'object' ? payload.right_panel : {});
    const anchors = Array.isArray(rightPanel?.anchor_sections) ? rightPanel.anchor_sections : [];
    const products = Array.isArray(payload?.products_summary) ? payload.products_summary : [];
    const normalizedEnvelope = String(event?.event_type || '').toLowerCase() !== 'recommendation_result';
    const score = (normalizedEnvelope ? 100 : 0) + (anchors.length ? 10 : 0) + (products.length ? 5 : 0);
    return [{ payload, score }];
  });
  candidates.sort((left, right) => right.score - left.score);
  return candidates[0]?.payload || null;
}

export function resolveSemanticProjection(trace: any, events: TraceProjectionEvent[], recommendation: any) {
  const eventPayload = [...(events || [])]
    .reverse()
    .map((event) => event?.payload || {})
    .find((payload) => payload?.semantic_resolution) || {};
  const rightPanel = recommendation?.right_panel_contract || {};
  return {
    semanticResolution: recommendation?.semantic_resolution
      || rightPanel.semantic_resolution
      || trace?.semantic_resolution
      || trace?.intent_analysis?.semantic_resolution
      || eventPayload.semantic_resolution
      || null,
    semanticEvidence: recommendation?.semantic_evidence
      || rightPanel.semantic_evidence
      || trace?.semantic_evidence
      || eventPayload.semantic_evidence
      || null,
    catalogAlignment: recommendation?.catalog_alignment
      || rightPanel.catalog_alignment
      || trace?.catalog_alignment
      || eventPayload.catalog_alignment
      || null,
    caseObligations: recommendation?.case_obligations
      || rightPanel.case_obligations
      || trace?.case_obligations
      || eventPayload.case_obligations
      || [],
  };
}

export function projectTraceDomains(events: TraceProjectionEvent[], imageTriage: any[] = []) {
  const corpus = JSON.stringify(events || []).toLowerCase();
  const procurementEvents = (events || []).filter((event: any) => {
    const source = String(event?.source_id || '').toLowerCase();
    const type = originalEventType(event);
    const payload = event?.payload || {};
    return source.includes('procurement') || source.includes('split') || source.includes('supplier')
      || source.includes('sourcing') || source.includes('integrity')
      || type.startsWith('bulk_') || type.startsWith('procurement_') || type.startsWith('alternatives_')
      || type.includes('availability') || type.includes('supplier') || type.includes('split')
      || type.includes('sourc') || type.includes('channel') || type.includes('integrity')
      || type === 'supplier_responses_normalized' || type === 'fulfillment_cart_change_confirmed'
      || Boolean(payload.delivery_feasibility || payload.human_escalation);
  });
  return {
    procurementEvents,
    outboundIntegrityEvents: (events || []).filter((event) => originalEventType(event).includes('outbound_integrity')),
    security: {
      present: /(security|quarantin|blocked|threat|risk|review_required)/.test(corpus),
      multimodal: Boolean(imageTriage?.length || /(image|multimodal|ocr|qr_|vision)/.test(corpus)),
      authority: 'evidence_only',
    },
    memory: { present: /(memory|cache|session|shortlist|nqe)/.test(corpus) },
  };
}

export function projectReasoningDomain({
  semanticResolution,
  semanticEvidence,
  catalogAlignment,
  caseObligations,
  executionSteps,
  modelSelection,
}: Record<string, any>) {
  return {
    interpretation: semanticResolution || null,
    evidence: semanticEvidence || null,
    catalogAlignment: catalogAlignment || null,
    obligations: Array.isArray(caseObligations) ? caseObligations : [],
    executionSteps: Array.isArray(executionSteps) ? executionSteps : [],
    complexity: modelSelection || null,
    authority: 'explanation_only',
  };
}
