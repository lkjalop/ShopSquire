/**
 * FulfilmentTraceLink — bridges the agent decision trace to the procurement journey.
 *
 * Given the turn's trace_id, it resolves the fulfilment case opened from that trace (linked by
 * source_trace_id) and renders the buyer-safe bitemporal journey inline. Renders NOTHING when no case
 * was opened for the turn — so it's a no-op on the common (no-procurement) path.
 */
import { useEffect, useState } from 'react';
import { getFulfillmentCaseByTrace } from '../lib/api';
import FulfilmentJourney from './FulfilmentJourney';

export default function FulfilmentTraceLink({ traceId }: { traceId?: string }) {
  const [caseId, setCaseId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setCaseId(null);
    if (!traceId) return;
    getFulfillmentCaseByTrace(traceId)
      .then((c) => { if (alive) setCaseId(c?.case_id || null); })
      .catch(() => { if (alive) setCaseId(null); });
    return () => { alive = false; };
  }, [traceId]);

  if (!caseId) return null;
  return (
    <section data-testid="trace-fulfilment-link" className="trace-fulfilment-link">
      <h4>Procurement journey for this decision <small>· {caseId.slice(0, 8)}</small></h4>
      <FulfilmentJourney caseId={caseId} />
    </section>
  );
}
