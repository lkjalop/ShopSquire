import { describe, it, expect } from 'vitest';
import { previousSessionSkus, keepAfterClear } from '../cartSession';

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

describe('keepAfterClear', () => {
  // session started with A+B (carried); buyer added C+D this session (C then D, D newest)
  const items = [{ sku: 'A', name: 'Alpha X1 Gaming' }, { sku: 'B', name: 'Beta Pro 14' },
                 { sku: 'C', name: 'Gamma Air 13' }, { sku: 'D', name: 'Delta ThinkPad L13' }];
  const initial = ['A', 'B'];

  it('the reported bug: "clear the cart but keep the latest" keeps the newest, does not wipe', () => {
    const r = keepAfterClear('clear the cart but keep the latest unit', items, initial);
    expect(r.isKeepClear).toBe(true);
    expect(r.keepSkus).toEqual(['D']);   // D = most-recently-added this session
  });

  it('"empty everything except the new one" → keeps this-session newest', () => {
    const r = keepAfterClear('empty everything except the new one', items, initial);
    expect(r.isKeepClear).toBe(true);
    expect(r.keepSkus).toEqual(['D']);
  });

  it('a NAMED item is kept by distinctive-token match', () => {
    const r = keepAfterClear('clear the cart but keep the ThinkPad', items, initial);
    expect(r.isKeepClear).toBe(true);
    expect(r.keepSkus).toEqual(['D']);   // only D's name has "thinkpad"
  });

  it('when all items are carried and "keep latest", falls back to the last cart line', () => {
    // nothing added this session → "latest" = last line overall
    const r = keepAfterClear('clear cart keep the last one', items, ['A', 'B', 'C', 'D']);
    expect(r.keepSkus).toEqual(['D']);
  });

  it('keep intent but UNRESOLVABLE target → isKeepClear true, empty keep set (caller ASKS, never wipes)', () => {
    const r = keepAfterClear('clear the cart but keep the Zenbook', items, initial);
    expect(r.isKeepClear).toBe(true);
    expect(r.keepSkus).toEqual([]);   // no cart line matches "zenbook" → ask, do not guess-then-wipe
  });

  it('a plain full-clear is NOT a keep-clear (falls through to the normal clear path)', () => {
    expect(keepAfterClear('clear my cart', items, initial).isKeepClear).toBe(false);
    expect(keepAfterClear('empty the cart', items, initial).isKeepClear).toBe(false);
  });

  it('an old-items scoped clear is NOT a keep-clear', () => {
    expect(keepAfterClear('clear the old items from my previous session', items, initial).isKeepClear).toBe(false);
  });

  it('empty cart → no keep set even if the phrasing matches', () => {
    const r = keepAfterClear('clear the cart but keep the latest', [], null);
    expect(r.keepSkus).toEqual([]);
  });
});
