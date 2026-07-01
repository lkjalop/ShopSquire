/**
 * SourcingIntentCard — the buyer-side FLUID-procurement preview + GATE-1 cart-confirmation. The endpoint
 * itself is proven by the Python cart_commitment suite; here we verify the card renders the preview and
 * calls confirm-cart with the previewed lines, and that it handles the amend-required signal.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../../lib/api', () => ({ confirmCartSourcing: vi.fn(), commitFulfillmentCase: vi.fn() }));
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
    (api.commitFulfillmentCase as any).mockResolvedValue({ ok: true });
    render(<SourcingIntentCard intent={INTENT} uid="u1" orderId="trace-1" traceId="trace-1" />);

    expect(screen.getByTestId('si-status')).toHaveTextContent(/needs confirmation before sourcing/i);
    // shortfall context is shown when it differs from the ordered qty
    expect(screen.getByTestId('si-lines')).toHaveTextContent(/MON-1 — 30 unit\(s\) \(14 to source\)/);

    fireEvent.click(screen.getByTestId('si-confirm-btn'));
    await waitFor(() => expect(screen.getByTestId('si-created')).toBeInTheDocument());
    expect(api.confirmCartSourcing).toHaveBeenCalledWith('u1', 'trace-1', INTENT.lines, 'trace-1', false, undefined);
    expect(api.commitFulfillmentCase).toHaveBeenCalledTimes(2);
    expect(api.commitFulfillmentCase).toHaveBeenCalledWith('a', 'u1');
    expect(api.commitFulfillmentCase).toHaveBeenCalledWith('b', 'u1');
    expect(screen.getByTestId('si-created')).toHaveTextContent(/Created 2 sourcing request\(s\)/);
    expect(screen.getByTestId('si-created')).toHaveTextContent(/No supplier has been contacted yet/i);
  });

  it('offers Supersede & re-source when the same order was confirmed with different items', async () => {
    (api.confirmCartSourcing as any)
      .mockResolvedValueOnce({  // first confirm → amend_required
        order_group_id: 'order-trace-1', case_count: 1, cases: [{ case_id: 'a' }],
        idempotent: false, amend_required: true, reason: 'order_lines_changed',
      })
      .mockResolvedValueOnce({  // supersede → retired old + created new
        order_group_id: 'order-trace-1', status: 'superseded', superseded: ['a'],
        created: { case_count: 1, cases: [{ case_id: 'b' }] },
      });
    (api.commitFulfillmentCase as any).mockResolvedValue({ ok: true });
    render(<SourcingIntentCard intent={INTENT} uid="u1" orderId="trace-1" />);
    fireEvent.click(screen.getByTestId('si-confirm-btn'));
    const supersedeBtn = await screen.findByTestId('si-supersede-btn');

    fireEvent.click(supersedeBtn);
    await waitFor(() => expect(screen.getByTestId('si-superseded')).toBeInTheDocument());
    expect(api.confirmCartSourcing).toHaveBeenLastCalledWith('u1', 'trace-1', INTENT.lines, undefined, true, undefined);
    expect(api.commitFulfillmentCase).not.toHaveBeenCalled();
    expect(screen.getByTestId('si-superseded')).toHaveTextContent(/retired 1 earlier request/i);
  });

  it('passes the buyer requirements (deadline/use_case) through to confirm-cart', async () => {
    (api.confirmCartSourcing as any).mockResolvedValue({ order_group_id: 'o', case_count: 1, cases: [{ case_id: 'a' }] });
    (api.commitFulfillmentCase as any).mockResolvedValue({ ok: true });
    const withReqs = { ...INTENT, requirements: { needed_by: '2026-07-07', use_case: 'office' } };
    render(<SourcingIntentCard intent={withReqs} uid="u1" orderId="trace-1" traceId="trace-1" />);
    fireEvent.click(screen.getByTestId('si-confirm-btn'));
    await waitFor(() => expect(api.confirmCartSourcing).toHaveBeenCalled());
    expect(api.confirmCartSourcing).toHaveBeenCalledWith('u1', 'trace-1', withReqs.lines, 'trace-1', false,
      { needed_by: '2026-07-07', use_case: 'office' });
  });

  it('shows a calm error when confirm fails', async () => {
    (api.confirmCartSourcing as any).mockRejectedValue(new Error('confirm_cart_failed (503)'));
    render(<SourcingIntentCard intent={INTENT} uid="u1" orderId="trace-1" />);
    fireEvent.click(screen.getByTestId('si-confirm-btn'));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('confirm_cart_failed (503)'));
  });
});
