import { describe, expect, it } from 'vitest';

import {
  resolveExecutionSteps,
  resolveRecommendationPayload,
  resolveSemanticProjection,
  projectReasoningDomain,
  projectTraceDomains,
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

  it('projects procurement, security and memory without event-text authority inference', () => {
    const projection = projectTraceDomains([
      { event_type: 'supplier_responses_normalized', payload: {} },
      { event_type: 'outbound_integrity_blocked', payload: {} },
      { event_type: 'cache_hit', payload: { security_status: 'review_required' } },
    ]);
    expect(projection.procurementEvents).toHaveLength(2);
    expect(projection.outboundIntegrityEvents).toHaveLength(1);
    expect(projection.security).toMatchObject({ present: true, authority: 'evidence_only' });
    expect(projection.memory.present).toBe(true);
  });

  it('combines why, intent, complexity and execution as explanation-only reasoning', () => {
    const projection = projectReasoningDomain({
      semanticResolution: { status: 'resolved' }, caseObligations: [{ id: 'fit' }],
      executionSteps: [{ kind: 'stage' }], modelSelection: { selected: 'local' },
    });
    expect(projection.authority).toBe('explanation_only');
    expect(projection.obligations).toHaveLength(1);
    expect(projection.executionSteps).toHaveLength(1);
  });
});
