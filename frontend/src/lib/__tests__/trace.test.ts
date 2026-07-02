import { describe, it, expect } from 'vitest';
import { procurementAwareTraceId } from '../trace';

describe('procurementAwareTraceId', () => {
  it('opens on the pinned sourcing trace when a procurement context exists', () => {
    // sourcing turn pinned trace A; a later upsell advanced traceId to B → still resolve procurement from A
    expect(procurementAwareTraceId('B', 'A', true)).toBe('A');
  });

  it('falls back to the current trace when no sourcing trace was pinned', () => {
    expect(procurementAwareTraceId('B', null, true)).toBe('B');
  });

  it('uses the current trace when there is no procurement context', () => {
    expect(procurementAwareTraceId('B', 'A', false)).toBe('B');
  });
});
