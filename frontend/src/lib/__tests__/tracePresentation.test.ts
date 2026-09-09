import { describe, expect, it } from 'vitest';
import {
  ACCESSORY_UPSELL_TRACE_LABEL,
  shouldShowMissingAnchorReasoning,
} from '../tracePresentation';

describe('trace presentation', () => {
  it('distinguishes the accessory trace from the primary decision trace', () => {
    expect(ACCESSORY_UPSELL_TRACE_LABEL).toBe('Accessory upsell trace');
  });

  it('does not claim reasoning is missing when ranked product evidence exists', () => {
    expect(shouldShowMissingAnchorReasoning([], [{ sku: 'LAP-1' }])).toBe(false);
    expect(shouldShowMissingAnchorReasoning([], [])).toBe(true);
  });
});
import { slateConsistencyLabel } from '../tracePresentation';

it('does not equate matching empty shelves with verified product fit', () => {
  expect(slateConsistencyLabel(true, true, 0)).toBe('Empty — no products');
  expect(slateConsistencyLabel(true, true, 2)).toBe('Matches recorded order');
  expect(slateConsistencyLabel(true, false, 2)).toBe('Mismatch — review required');
  expect(slateConsistencyLabel(false, false, 0)).toBe('Not recorded');
});
