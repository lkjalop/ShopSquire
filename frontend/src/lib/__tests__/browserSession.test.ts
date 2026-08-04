import { beforeEach, describe, expect, it } from 'vitest';

import {
  getOrCreateConversationEpoch,
  rotateConversationEpoch,
} from '../browserSession';

describe('conversation epoch isolation', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('keeps an epoch stable until the user starts a new privacy boundary', () => {
    const first = getOrCreateConversationEpoch();
    expect(getOrCreateConversationEpoch()).toBe(first);

    const next = rotateConversationEpoch();
    expect(next).not.toBe(first);
    expect(getOrCreateConversationEpoch()).toBe(next);
  });
});
