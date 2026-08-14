import { describe, expect, it } from 'vitest';

import { projectMarketHippographTrace } from '../marketHippographProjection';

const matches = (event: any, expected: string) => event.event_type === expected;

describe('market and Hippograph trace projection', () => {
  it('separates market evidence and deduplicates Hippograph paths', () => {
    const projection = projectMarketHippographTrace({
      trace: { hippograph_insights: [{ id: 'path-1', label: 'one' }] },
      events: [
        { event_type: 'market_projection', payload: { sku: 'SKU-1' } },
        { event_type: 'market_cohort_behavior', payload: { status: 'aggregated' } },
        { event_type: 'other', payload: { evidence_paths: [{ id: 'path-1' }, { id: 'path-2' }] } },
      ],
      eventMatcher: matches,
    });
    expect(projection.marketProjectionEvents).toHaveLength(1);
    expect(projection.marketBehaviorEvents).toHaveLength(1);
    expect(projection.hippographInsights.map((row) => row.id)).toEqual(['path-1', 'path-2']);
  });
});
