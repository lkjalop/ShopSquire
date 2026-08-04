import { describe, expect, it } from 'vitest';
import { buildUnifiedCaseTimeline } from './CaseJourney';

describe('unified procurement activity', () => {
  it('orders case and communication evidence and marks prevented effects', () => {
    const activity = buildUnifiedCaseTimeline(
      [{
        state: 'QUOTE_SENT', event: 'dispatch', actor_type: 'human_operator',
        actor_id: 'op', valid_from: '2026-07-01T10:00:00Z',
      }],
      [{
        event_id: 'evt-1', observation_id: 'obs-1', state: 'quarantined',
        actor_type: 'security_boundary', commercial_effect: 'prevented',
        occurred_at: '2026-07-01T10:01:00Z', reason: 'unsafe_instruction',
      }],
    );

    expect(activity.map((event) => event.kind)).toEqual(['case', 'communication']);
    expect(activity[0].effect).toBe('changed');
    expect(activity[1]).toMatchObject({ effect: 'prevented', state: 'quarantined' });
  });
});
