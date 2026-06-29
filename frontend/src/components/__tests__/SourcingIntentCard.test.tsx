/**
 * SourcingIntentCard — the buyer-side FLUID-procurement preview + GATE-1 cart-confirmation. The endpoint
 * itself is proven by the Python cart_commitment suite; here we verify the card renders the preview and
 * calls confirm-cart with the previewed lines, and that it handles the amend-required signal.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../../lib/api', () => ({ confirmCartSourcing: vi.fn() }));
import * as api from '../../lib/api';
import SourcingIntentCard from '../SourcingIntentCard';

const INTENT = {
  mode: 'deferred_to_cart',
  planned_case_count: 2,
  lines: [
    { item_ref: 'GAM-0002', quantity: 7 },
    { item_ref: 'MON-1', quantity: 30, shortfall: 14 },
  ],
};

beforeEach(() => { vi.clearAllMocks(); });

describe('SourcingIntentCard', () => {
  it('renders the preview (no supplier named) and confirms via /confirm-cart with the previewed lines', async () => {
    (api.confirmCartSourcing as any).mockResolvedValue({
      order_group_id: 'order-trace-1', case_count: 2, cases: [{ case_id: 'a' }, { case_id: 'b' }], idempotent: false,
    });
    render(<SourcingIntentCard intent={INTENT} uid="u1" orderId="trace-1" traceId="trace-1" />);

    expect(screen.getByTestId('si-status')).toHaveTextContent(/needs confirmation before sourcing/i);
    // shortfall context is shown when it differs from the ordered qty
    expect(screen.getByTestId('si-lines')).toHaveTextContent(/MON-1 — 30 unit\(s\) \(14 to source\)/);

    fireEvent.click(screen.getByTestId('si-confirm-btn'));
    await waitFor(() => expect(screen.getByTestId('si-created')).toBeInTheDocument());
    expect(api.confirmCartSourcing).toHaveBeenCalledWith('u1', 'trace-1', INTENT.lines, 'trace-1');
    expect(screen.getByTestId('si-created')).toHaveTextContent(/Created 2 sourcing request\(s\)/);
    expect(screen.getByTestId('si-created')).toHaveTextContent(/No supplier has been contacted yet/i);
  });

  it('surfaces amend_required when the same order was confirmed with different items', async () => {
    (api.confirmCartSourcing as any).mockResolvedValue({
      order_group_id: 'order-trace-1', case_count: 1, cases: [{ case_id: 'a' }],
      idempotent: false, amend_required: true, reason: 'order_lines_changed',
    });
    render(<SourcingIntentCard intent={INTENT} uid="u1" orderId="trace-1" />);
    fireEvent.click(screen.getByTestId('si-confirm-btn'));
    await waitFor(() => expect(screen.getByTestId('si-amend')).toBeInTheDocument());
    expect(screen.getByTestId('si-amend')).toHaveTextContent(/amendment is required/i);
  });

  it('shows a calm error when confirm fails', async () => {
    (api.confirmCartSourcing as any).mockRejectedValue(new Error('confirm_cart_failed (503)'));
    render(<SourcingIntentCard intent={INTENT} uid="u1" orderId="trace-1" />);
    fireEvent.click(screen.getByTestId('si-confirm-btn'));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('confirm_cart_failed (503)'));
  });
});
