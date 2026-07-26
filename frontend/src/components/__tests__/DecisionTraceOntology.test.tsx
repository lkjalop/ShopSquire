import { describe, expect, it } from 'vitest';

import {
  compactAuthorityPath,
  legacyComponentOntology,
  resolveWhyAnchorSections,
} from '../DecisionTrace';

describe('Decision Trace component ontology', () => {
  it('reserves agent authority for model-directed components', () => {
    expect(legacyComponentOntology('Recommendation_Agent')).toMatchObject({
      kind: 'model',
      authority: 'proposes',
    });
    expect(legacyComponentOntology('Procurement_Agent')).toMatchObject({
      kind: 'stage',
      authority: 'executes',
    });
  });

  it('describes market intelligence as evidence retrieval', () => {
    expect(legacyComponentOntology('Market_Intelligence_Agent')).toMatchObject({
      kind: 'connector',
      authority: 'retrieves',
    });
  });

  it('uses the later right-panel event when persistence preceded anchor construction', () => {
    const anchors = [{ title: 'Matched to your query', top_products: [{ sku: 'A' }] }];
    expect(resolveWhyAnchorSections(
      { right_panel: { anchor_sections: [] } },
      [
        {
          event_type: 'recommendation_result',
          payload: { right_panel_contract: { anchor_sections: [] } },
        },
        {
          event_type: 'right_panel_anchor_sections',
          payload: { right_panel_contract: { anchor_sections: anchors } },
        },
      ],
    )).toEqual(anchors);
  });

  it('compacts repeated stage execution without hiding authority boundaries', () => {
    expect(compactAuthorityPath([
      { authority: 'proposes' },
      { authority: 'authorizes' },
      { authority: 'executes' },
      { authority: 'executes' },
      { authority: 'executes' },
      { authority: 'authorizes' },
      { authority: 'presents' },
    ])).toBe('proposes -> authorizes -> executes (3 stages) -> authorizes -> presents');
  });
});
