/**
 * FulfilmentJourney — the buyer-safe view of a procurement case's bitemporal history.
 *
 * Renders only the safe transition fields (event · state · actor · time) — never the per-event
 * evidence payload (which can hold supplier-private data). The operator room shows the full journey;
 * this is the buyer's "View journey" surface, derived from the same /journey endpoint.
 */
import { useEffect, useState } from 'react';
import { getFulfillmentJourney } from '../lib/api';

interface JourneyEvent {
  state: string; event: string; actor_type: string; reason_code?: string; valid_from?: string;
}

export default function FulfilmentJourney({ caseId }: { caseId: string }) {
  const [events, setEvents] = useState<JourneyEvent[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    getFulfillmentJourney(caseId)
      .then((d: any) => { if (alive) setEvents(Array.isArray(d?.journey) ? d.journey : []); })
      .catch((e: any) => { if (alive) setError(e?.message || 'could not load journey'); });
    return () => { alive = false; };
  }, [caseId]);

  if (error) return <p role="alert" data-testid="fj-error">{error}</p>;
  return (
    <ol data-testid="fulfilment-journey" className="fulfilment-journey">
      {events.map((e, i) => (
        <li key={i} data-testid="fj-event">
          <code>{e.event}</code> → <strong>{e.state.replace(/_/g, ' ').toLowerCase()}</strong>
          <span className="fj-actor"> · {e.actor_type}</span>
          {e.valid_from && <small className="fj-time"> · {e.valid_from}</small>}
        </li>
      ))}
      {events.length === 0 && !error && <li><em>no steps yet</em></li>}
    </ol>
  );
}
