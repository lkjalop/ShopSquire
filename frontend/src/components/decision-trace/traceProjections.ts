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
