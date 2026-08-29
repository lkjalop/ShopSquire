import { describe, expect, it } from 'vitest';

import { isActionableBuyerQuestion, isResearchAuthorityQuestion } from './buyerQuestion';

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

describe('isResearchAuthorityQuestion', () => {
  it('keeps material research consent in the dedicated identity/research card', () => {
    expect(isResearchAuthorityQuestion({
      id: 'workload_requirements', goal: 'resolve_named_workload',
      text: 'May I check enrolled official sources?', options: [],
    })).toBe(true);
    expect(isResearchAuthorityQuestion({
      id: 'ask_budget', goal: 'narrow_results', text: 'What budget?', options: [],
    })).toBe(false);
  });
});
