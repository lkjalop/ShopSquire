import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ReturnLifecycleTrace, { returnLifecycleProjection } from '../ReturnLifecycleTrace';

describe('ReturnLifecycleTrace', () => {
  it('shows authority, typed order failure and prevented consequential state', () => {
    const events = [{ event_type: 'return_claim_evidence_pending', timestamp: '2026-08-04T01:00:00Z', payload: {
      claim_id: 'claim-1', status: 'evidence_pending', evidence_count: 2,
      order_verification_status: 'source_unavailable', authority: 'observation_only',
      commercial_action_prevented: true,
    }}];
    render(<ReturnLifecycleTrace events={events} />);
    expect(screen.getByText(/Order service unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/no refund, replacement or repair authorization/i)).toBeInTheDocument();
    expect(screen.getByText(/observation only/i)).toBeInTheDocument();
  });

  it('preserves the append-only lifecycle ordering', () => {
    const view = returnLifecycleProjection([
      { event_type: 'return_claim_evidence_pending', payload: { status: 'evidence_pending' } },
      { event_type: 'return_claim_status_changed', payload: { to_status: 'under_review' } },
    ]);
    expect(view?.timeline.map((event) => event.status)).toEqual(['evidence_pending', 'under_review']);
  });
});
