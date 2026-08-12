import { describe, expect, it } from 'vitest';

import { pendingCartPlanFromHumanEvent } from '../../lib/humanCartProposal';

describe('pendingCartPlanFromHumanEvent', () => {
  it('projects a staff proposal into the canonical buyer confirmation shape', () => {
    expect(pendingCartPlanFromHumanEvent({
      plan_id: 'cmp-human-1',
      expires_at: '2026-08-12T11:00:00Z',
      plan: { ops: [{ action: 'replace_item', target_skus: ['A'], replacement_sku: 'B', quantity: 30 }] },
    })).toEqual({
      planId: 'cmp-human-1',
      expiresAt: '2026-08-12T11:00:00Z',
      ops: [{ action: 'replace_item', target_skus: ['A'], replacement_sku: 'B', quantity: 30 }],
    });
  });

  it('rejects messages that do not contain a durable plan id and operations', () => {
    expect(pendingCartPlanFromHumanEvent({ plan: { ops: [] } })).toBeNull();
    expect(pendingCartPlanFromHumanEvent(null)).toBeNull();
  });
});
