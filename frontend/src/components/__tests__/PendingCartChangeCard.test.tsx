import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import PendingCartChangeCard from '../PendingCartChangeCard';

describe('PendingCartChangeCard', () => {
  it('enumerates every operation and makes additive arithmetic explicit', () => {
    const onConfirm = vi.fn();
    render(
      <PendingCartChangeCard
        plan={{
          planId: 'cmp-53',
          ops: [
            {
              action: 'set_quantity',
              target_skus: ['LAP-ASUS'],
              previous_quantity: 30,
              quantity: 60,
              unit_price_cents: 489400,
              allow_sourcing: true,
            },
            { action: 'remove_items', target_skus: ['LAP-LENOVO'] },
          ],
          expiresAt: '2099-01-01 12:30:00',
        }}
        cartItems={[
          { sku: 'LAP-ASUS', name: 'ASUS ProArt 16', quantity: 30, price_cents: 489400, currency: 'AUD' },
          { sku: 'LAP-LENOVO', name: 'Lenovo Legion Pro 7', quantity: 30, price_cents: 599900, currency: 'AUD' },
        ]}
        onConfirm={onConfirm}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.getByText(/30 \+ 30 = 60 units/)).toBeTruthy();
    expect(screen.getByText(/Lenovo Legion Pro 7: 30 → 0 units/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Apply all 2 changes' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('discards without applying', () => {
    const onConfirm = vi.fn();
    const onDismiss = vi.fn();
    render(
      <PendingCartChangeCard
        plan={{ planId: 'cmp-1', ops: [{ action: 'clear_all' }] }}
        onConfirm={onConfirm}
        onDismiss={onDismiss}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Discard plan' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
