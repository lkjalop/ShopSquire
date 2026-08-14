type TraceEvent = { event_type?: string; payload?: Record<string, any> };

export type MarketHippographProjection = {
  marketProjectionEvents: TraceEvent[];
  marketBehaviorEvents: TraceEvent[];
  hippographInsights: any[];
};

export function projectMarketHippographTrace({
  events,
  trace,
  eventMatcher,
}: {
  events: TraceEvent[];
  trace?: Record<string, any> | null;
  eventMatcher: (event: TraceEvent, expected: string) => boolean;
}): MarketHippographProjection {
  const candidates: any[] = [];
  const append = (value: any) => {
    if (Array.isArray(value)) candidates.push(...value);
  };
  append(trace?.hippograph_insights);
  append(trace?.hippograph_shadow_insights);
  events.forEach((event) => {
    append(event?.payload?.hippograph_insights);
    append(event?.payload?.hippograph_shadow_insights);
    append(event?.payload?.evidence_paths);
  });
  const seen = new Set<string>();
  const hippographInsights = candidates.filter((insight, index) => {
    if (!insight || typeof insight !== 'object') return false;
    const key = String(
      insight.id || insight.evidence_path?.path_id || `${insight.label || 'insight'}-${index}`,
    );
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return {
    marketProjectionEvents: events.filter((event) => eventMatcher(event, 'market_projection')),
    marketBehaviorEvents: events.filter((event) => eventMatcher(event, 'market_cohort_behavior')),
    hippographInsights,
  };
}
