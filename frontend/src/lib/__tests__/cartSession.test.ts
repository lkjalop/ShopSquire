import { describe, it, expect } from 'vitest';
import { previousSessionSkus } from '../cartSession';

describe('previousSessionSkus', () => {
  it('items present at session start and still in the cart are previous-session', () => {
    expect(previousSessionSkus(['A', 'B', 'C'], ['A', 'B'])).toEqual(['A', 'B']);
  });

  it('items added THIS session are never labelled previous', () => {
    // session started with A; buyer added X and Y → only A is clearable-as-previous
    expect(previousSessionSkus(['A', 'X', 'Y'], ['A'])).toEqual(['A']);
  });

  it('a session that starts empty never labels anything previous', () => {
    expect(previousSessionSkus(['X', 'Y'], [])).toEqual([]);
    expect(previousSessionSkus(['X'], null)).toEqual([]);   // snapshot not yet taken
  });

  it('previous items the buyer already removed do not reappear', () => {
    // started with A+B; buyer removed B themselves → only A remains previous
    expect(previousSessionSkus(['A', 'X'], ['A', 'B'])).toEqual(['A']);
  });
});
