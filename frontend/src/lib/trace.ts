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
