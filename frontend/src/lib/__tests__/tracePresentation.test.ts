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
