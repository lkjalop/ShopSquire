import { describe, it, expect } from 'vitest';
import { nextSourcingTraceId, procurementAwareTraceId } from '../trace';

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

describe('nextSourcingTraceId', () => {
  it('pins a V2 bulk turn that starts with fulfilment alternatives', () => {
    expect(nextSourcingTraceId(null, 'recommendation-trace', false, true, true))
      .toBe('recommendation-trace');
  });

  it('does not replace the sourcing decision with a later cart mutation trace', () => {
    expect(nextSourcingTraceId('recommendation-trace', 'cart-trace', false, false, true))
      .toBe('recommendation-trace');
  });

  it('releases the pin when the procurement context is gone', () => {
    expect(nextSourcingTraceId('recommendation-trace', 'search-trace', false, false, false))
      .toBeNull();
  });
});
