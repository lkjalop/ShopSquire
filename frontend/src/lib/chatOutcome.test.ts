import { describe, expect, it } from 'vitest';

import { nonRecommendationOutcome } from './chatOutcome';

describe('nonRecommendationOutcome', () => {
  it('types quota blocks as non-mutating UI outcomes', () => {
    expect(nonRecommendationOutcome({ blocked: true, quota_reason: 'quota:daily_token_limit' })).toEqual({
      kind: 'blocked',
      message: 'AI narration is unavailable for this request. Your product, cart, and procurement case are unchanged. (quota:daily_token_limit)',
      preserveCurrentView: true,
      authority: 'no_state_change',
    });
  });

  it('preserves a truthful backend explanation', () => {
    expect(nonRecommendationOutcome({ degraded: true, assistant_message: 'Catalog timed out; status is unchanged.' }))?.toMatchObject({
      kind: 'degraded',
      message: 'Catalog timed out; status is unchanged.',
      preserveCurrentView: true,
    });
  });

  it('does not intercept ordinary recommendation payloads', () => {
    expect(nonRecommendationOutcome({ products: [{ sku: 'RGAM-0007' }] })).toBeNull();
  });

  it('does not hide a typed provisional case when one execution stage degraded', () => {
    expect(nonRecommendationOutcome({
      degraded: true,
      ambiguity_exploration: { schema_version: 'ambiguity-exploration-v1' },
    })).toBeNull();
  });
});
