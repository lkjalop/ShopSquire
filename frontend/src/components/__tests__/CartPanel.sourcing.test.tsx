import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../../lib/api', () => ({
  apiUrl: (path: string) => `http://localhost${path}`,
  safeJson: vi.fn(async () => ({ results: [] })),
  confirmCartSourcing: vi.fn(),
  commitFulfillmentCase: vi.fn(),
  getSplitOffer: vi.fn(),
}));

import * as api from '../../lib/api';
import CartPanel from '../CartPanel';

const item = { sku: 'LAP-1', quantity: 20, price_cents: 119900, name: 'Business laptop' };
const cart = (quantity: number) => ({
  cart_id: 'cart-1',
  currency: 'AUD',
  subtotal_cents: quantity * 119900,
  items: [{ ...item, quantity }],
});

const splitOffer = (quantity: number) => ({
  cart_id: 'cart-1',
  subtotal_cents: quantity * 119900,
  currency: 'AUD',
  split: {
    now: [{ sku: 'LAP-1', qty: Math.min(quantity, 15), unit_cents: 119900 }],
    later: quantity > 15 ? [{ sku: 'LAP-1', qty: quantity - 15, unit_cents: 119900, eta_days: 6, supplier_ref: 'SUP-BIZ' }] : [],
    fully_in_stock: quantity <= 15,
    rationale: quantity > 15 ? 'Split shipment required.' : 'Fully in stock.',
    delivery: { currency: 'AUD', fee_now_cents: 0, fee_later_cents: 0, total_fee_cents: 0, shipments: quantity > 15 ? 2 : 1 },
  },
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true })));
});

describe('CartPanel sourcing amendments', () => {
  it('blocks checkout and retires the prior RFQ when amended demand is fully in stock', async () => {
    (api.getSplitOffer as any)
      .mockResolvedValueOnce(splitOffer(20))
      .mockResolvedValueOnce(splitOffer(15));
    (api.confirmCartSourcing as any)
      .mockResolvedValueOnce({ case_count: 1, cases: [{ case_id: 'case-1' }], idempotent: false })
      .mockResolvedValueOnce({ case_count: 1, cases: [{ case_id: 'case-1' }], amend_required: true })
      .mockResolvedValueOnce({ status: 'superseded', superseded: ['case-1'], created: { case_count: 0, cases: [] } });
    (api.commitFulfillmentCase as any).mockResolvedValue({ state: 'QUOTE_DRAFTED' });

    const props = {
      uid: 'u1', onRefresh: vi.fn(), onRemove: vi.fn(), onClear: vi.fn(), onAdd: vi.fn(),
      traceId: 'trace-1', sourcingOrderId: 'pr-1',
    };
    const view = render(<CartPanel {...props} cart={cart(20)} />);

    fireEvent.click(await screen.findByTestId('split-confirm'));
    await waitFor(() => expect(screen.getByTestId('cart-proceed')).toBeInTheDocument());

    view.rerender(<CartPanel {...props} cart={cart(15)} />);
    expect(await screen.findByTestId('cart-sourcing-stale')).toHaveTextContent(/prior RFQ will be superseded/i);
    expect(screen.queryByTestId('cart-proceed')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('cart-confirm-updated-plan'));
    await waitFor(() => expect(screen.getByTestId('cart-sourcing-note')).toHaveTextContent(/previous supplier request was retired/i));
    expect(api.confirmCartSourcing).toHaveBeenLastCalledWith('u1', 'pr-1', [{ item_ref: 'LAP-1', quantity: 15 }], 'trace-1', true, undefined);
    expect(api.commitFulfillmentCase).toHaveBeenCalledTimes(1);
  });
});
