import { useEffect, useMemo, useState } from 'react';

import { apiUrl, safeJson } from '../lib/api';
import { projectMarketHippographTrace } from '../components/decision-trace/marketHippographProjection';

type TraceEvent = { event_type?: string; payload?: Record<string, any> };

export function useMarketHippographTrace({
  active,
  events,
  trace,
  apiKey,
  eventMatcher,
}: {
  active: boolean;
  events: TraceEvent[];
  trace?: Record<string, any> | null;
  apiKey?: string;
  eventMatcher: (event: TraceEvent, expected: string) => boolean;
}) {
  const projection = useMemo(() => projectMarketHippographTrace({
    events, trace, eventMatcher,
  }), [events, trace, eventMatcher]);
  const [connectorHealth, setConnectorHealth] = useState<any | null>(null);
  const [connectorHealthStatus, setConnectorHealthStatus] = useState<
    'not_requested' | 'loading' | 'available' | 'unavailable'
  >('not_requested');

  useEffect(() => {
    if (!active || !apiKey) {
      setConnectorHealthStatus('not_requested');
      return undefined;
    }
    const controller = new AbortController();
    const deadline = window.setTimeout(() => controller.abort(), 5000);
    setConnectorHealthStatus('loading');
    fetch(apiUrl('/api/v1/admin/market-ingestion/health'), {
      credentials: 'include', signal: controller.signal, headers: { 'x-api-key': apiKey },
    })
      .then(async (response) => {
        const payload = await safeJson(response);
        if (!response.ok) throw new Error(`market_health_${response.status}`);
        setConnectorHealth(payload);
        setConnectorHealthStatus('available');
      })
      .catch(() => {
        if (!controller.signal.aborted) setConnectorHealth(null);
        setConnectorHealthStatus('unavailable');
      })
      .finally(() => window.clearTimeout(deadline));
    return () => {
      window.clearTimeout(deadline);
      controller.abort();
    };
  }, [active, apiKey]);

  return { ...projection, connectorHealth, connectorHealthStatus };
}
