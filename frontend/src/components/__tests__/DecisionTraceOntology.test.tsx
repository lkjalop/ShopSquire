import { describe, expect, it } from 'vitest';

import { legacyComponentOntology } from '../DecisionTrace';

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
});
