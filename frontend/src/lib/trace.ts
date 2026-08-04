/**
 * Which decision trace should the Decision Trace modal open on?
 *
 * When a procurement context exists this turn (a sourcing preview, an open fulfilment case, or bulk
 * alternatives), open on the SOURCING turn's pinned trace — otherwise a later upsell/add turn would have
 * advanced `traceId` past the decision that opened the procurement journey, and the Procurement tab/badge
 * (which resolves the case by source_trace_id) would show nothing. With no procurement context, use the
 * current trace as normal. Pure + deterministic so it's unit-testable in isolation.
 */
export function procurementAwareTraceId(
  traceId: string | null,
  sourcingTraceId: string | null,
  hasProcurementContext: boolean,
): string | null {
  return hasProcurementContext ? (sourcingTraceId || traceId) : traceId;
}

/**
 * Keep the recommendation decision that opened a sourcing journey stable while cart mutations
 * create their own audit traces. A sourcing journey can begin with either a deferred sourcing
 * intent or bounded fulfilment alternatives; requiring only the former loses V2 bulk turns.
 */
export function nextSourcingTraceId(
  currentSourcingTraceId: string | null,
  nextTraceId: string | null,
  hasSourcingPreview: boolean,
  hasFulfillmentOptions: boolean,
  hasProcurementContext: boolean,
): string | null {
  if ((hasSourcingPreview || hasFulfillmentOptions) && nextTraceId) return nextTraceId;
  if (!hasProcurementContext) return null;
  return currentSourcingTraceId;
}
