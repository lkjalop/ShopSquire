/** Presentation binding only; backend ownership checks remain authoritative. */
export function boundTurnProjection(value: any, traceId: string | null): any | null {
  if (!traceId?.trim() || value?.schema_version !== 'revision-bound-turn-read-model.v1') return null;
  if (value.trace_id !== traceId.trim() || typeof value.case_id !== 'string' || !value.case_id.trim()) return null;
  if (!Number.isInteger(value.case_revision) || value.case_revision < 1) return null;
  return value;
}

export function boundResearchOutcome(value: any, projection: any): any | null {
  if (!projection || value?.case_id !== projection.case_id || value?.case_revision !== projection.case_revision) return null;
  return value?.schema_version === 'research-outcome-v1' ? value : null;
}

export function boundImageTriage(items: any[] | undefined, traceId: string | null): any[] {
  if (!Array.isArray(items)) return [];
  // A direct inspection without a selected decision is a supported local view.
  if (!traceId?.trim()) return items;
  return items.filter(item => {
    const id = item?.artifact?.artifact_id || item?.decision_trace_id || item?.trace_id || item?.decision_id;
    return id === traceId.trim();
  });
}
