import { describe, expect, it } from 'vitest';

import { isActionableBuyerQuestion } from './buyerQuestion';

describe('isActionableBuyerQuestion', () => {
  it('keeps questions and option prompts', () => {
    expect(isActionableBuyerQuestion({ text: 'Which workload runs locally?' })).toBe(true);
    expect(isActionableBuyerQuestion({ text: 'Choose a scope', options: ['local'] })).toBe(true);
  });

  it('rejects infrastructure refusals and status messages', () => {
    expect(isActionableBuyerQuestion({
      text: 'I could not obtain approved requirements, so product fit remains provisional.',
    })).toBe(false);
    expect(isActionableBuyerQuestion({ text: 'Discovery is degraded.' })).toBe(false);
  });
});
