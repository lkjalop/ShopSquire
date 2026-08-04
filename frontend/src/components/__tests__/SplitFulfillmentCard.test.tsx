/**
 * SplitFulfillmentCard — the pre-payment split disclosure. The split math is proven by the Python
 * fulfillment_split suite; here we verify the card fetches the offer, renders now/later with the SUPPLIER's
 * real ETA + the delivery terms, hides itself when the cart is fully in stock, and reports its confirm state.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../../lib/api', () => ({ getSplitOffer: vi.fn() }));
import * as api from '../../lib/api';
import SplitFulfillmentCard from '../SplitFulfillmentCard';

const SPLIT = {
  cart_id: 'c1', subtotal_cents: 4604500, currency: 'USD',
  split: {
    now: [{ sku: 'LAP-1', qty: 22, unit_cents: 139900 }],
    later: [{ sku: 'LAP-1', qty: 3, unit_cents: 139900, eta_days: 6, supplier_ref: 'SUP-BIZ' }],
    subtotal_cents: 4604500, fully_in_stock: false,
    rationale: 'Ship the 22 in-stock unit(s) now; the remaining 3 follow in ~6 days (supplier lead time).',
    delivery: {
      currency: 'USD', fee_now_cents: 0, fee_later_cents: 0, total_fee_cents: 0,
      free_shipping_threshold_cents: 500000, waived: true, shipments: 2, backorder_enabled: true,
    },
  },
};
const nameFor = (sku: string) => (sku === 'LAP-1' ? 'Surface Pro' : sku);
beforeEach(() => { vi.clearAllMocks(); });

describe('SplitFulfillmentCard', () => {
  it('renders now/later with the real supplier ETA + delivery, and confirms the plan', async () => {
    (api.getSplitOffer as any).mockResolvedValue(SPLIT);
    const onSplitState = vi.fn();
    render(<SplitFulfillmentCard uid="u1" refreshKey="LAP-1:25" nameFor={nameFor} onSplitState={onSplitState} />);

    await waitFor(() => expect(screen.getByTestId('split-fulfillment-card')).toBeInTheDocument());
    expect(screen.getByTestId('split-rationale')).toHaveTextContent(/remaining 3 follow in ~6 days/);
    // the backordered line shows the SUPPLIER's real ETA + ref (not a guess)
    expect(screen.getByTestId('split-eta-LAP-1')).toHaveTextContent(/~6 days · SUP-BIZ/);
    // free-shipping threshold waives the fee
    expect(screen.getByTestId('split-delivery')).toHaveTextContent(/Free delivery — order over \$5,000/);
    // parent is told a split exists but is not yet confirmed
    expect(onSplitState).toHaveBeenCalledWith(true, false);

    fireEvent.click(screen.getByTestId('split-confirm'));
    expect(screen.getByTestId('split-confirmed')).toBeInTheDocument();
    expect(onSplitState).toHaveBeenLastCalledWith(true, true);
  });

  it('renders nothing when the cart is fully in stock (no second shipment to disclose)', async () => {
    (api.getSplitOffer as any).mockResolvedValue({
      ...SPLIT, split: { ...SPLIT.split, later: [], fully_in_stock: true },
    });
    const onSplitState = vi.fn();
    const { container } = render(
      <SplitFulfillmentCard uid="u1" refreshKey="LAP-1:5" nameFor={nameFor} onSplitState={onSplitState} />);
    await waitFor(() => expect(onSplitState).toHaveBeenCalledWith(false, false));
    expect(container.querySelector('[data-testid="split-fulfillment-card"]')).toBeNull();
  });

  it('separates confirmed network transfers from the unconfirmed supplier RFQ', async () => {
    (api.getSplitOffer as any).mockResolvedValue({
      ...SPLIT,
      split: {
        ...SPLIT.split,
        now: [{ sku: 'LAP-1', qty: 5, unit_cents: 139900 }],
        transfers: [{ sku: 'LAP-1', qty: 17, unit_cents: 139900 }],
        later: [{ sku: 'LAP-1', qty: 3, unit_cents: 139900, eta_days: 6, supplier_ref: 'SUP-BIZ' }],
      },
    });
    render(<SplitFulfillmentCard uid="u1" refreshKey="LAP-1:25" nameFor={nameFor} />);
    await waitFor(() => expect(screen.getByTestId('split-transfer-LAP-1')).toBeInTheDocument());
    expect(screen.getByTestId('split-transfer-LAP-1')).toHaveTextContent('confirmed internal stock');
    expect(screen.getByText('Requires supplier RFQ')).toBeInTheDocument();
    expect(screen.getByTestId('split-eta-LAP-1')).toHaveTextContent(/supplier lead time ~6 days/);
  });

  it('stays hidden and reports no split when the offer fetch fails (best-effort, never blocks the cart)', async () => {
    (api.getSplitOffer as any).mockRejectedValue(new Error('split_offer_failed (503)'));
    const onSplitState = vi.fn();
    const { container } = render(
      <SplitFulfillmentCard uid="u1" refreshKey="LAP-1:25" nameFor={nameFor} onSplitState={onSplitState} />);
    await waitFor(() => expect(api.getSplitOffer).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="split-fulfillment-card"]')).toBeNull();
    expect(onSplitState).toHaveBeenLastCalledWith(false, false);
  });
});
