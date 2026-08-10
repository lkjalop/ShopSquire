import { describe, expect, it } from 'vitest';

import { isUnsupportedPostPurchaseTracking } from '../postPurchaseIntent';

describe('post-purchase tracking boundary', () => {
  it.each([
    'Where is my order?',
    'Track order ABC-123',
    'What is the status of my delivery?',
    'When will my existing delivery arrive?',
    'Has my order shipped?',
  ])('recognizes an unsupported existing-order request: %s', (query) => {
    expect(isUnsupportedPostPurchaseTracking(query)).toBe(true);
  });

  it.each([
    'I need 15 of the top one. When can they all arrive?',
    'When can 15 arrive?',
    'Can all 30 be delivered within ten days?',
    'How many can ship now?',
    'I need 40 within 3 days.',
  ])('allows a prospective fulfilment request to reach the backend: %s', (query) => {
    expect(isUnsupportedPostPurchaseTracking(query)).toBe(false);
  });
});
