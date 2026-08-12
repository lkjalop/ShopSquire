import { describe, expect, it } from 'vitest';

import {
  resolveExecutionSteps,
  resolveRecommendationPayload,
  resolveSemanticProjection,
} from '../traceProjections';

describe('Decision Trace projections', () => {
  it('prefers typed trace execution over persisted fallback', () => {
    const persisted = [{ kind: 'connector', source_id: 'search' }];
    const typed = [{ kind: 'stage', source_id: 'fit' }];
    expect(resolveExecutionSteps({ execution_steps: typed }, [{ payload: { execution_steps: persisted } }])).toBe(typed);
    expect(resolveExecutionSteps({}, [{ payload: { execution_steps: persisted } }])).toBe(persisted);
  });

  it('selects the richest normalized recommendation envelope', () => {
    const plain = { event_type: 'recommendation_result', payload: { products_summary: [{ sku: 'OLD' }] } };
    const normalized = {
      event_type: 'feedback_loop',
      payload: {
        _original_event_type: 'recommendation_result',
        products_summary: [{ sku: 'NEW' }],
        right_panel_contract: { anchor_sections: [{ id: 'fit' }] },
      },
    };
    expect(resolveRecommendationPayload([plain, normalized])?.products_summary?.[0]?.sku).toBe('NEW');
  });

  it('keeps semantic evidence visible when recommendation scoring has no payload', () => {
    const projection = resolveSemanticProjection({}, [{ payload: { semantic_resolution: { status: 'unresolved' } } }], null);
    expect(projection.semanticResolution).toEqual({ status: 'unresolved' });
    expect(projection.caseObligations).toEqual([]);
  });
});
