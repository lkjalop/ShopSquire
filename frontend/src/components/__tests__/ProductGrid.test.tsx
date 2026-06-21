/**
 * ProductGrid — stock-honesty UX (Workstream A).
 * The backend finalizer emits stock_status/stock_urgency/cart_eligible per item; the grid must
 * surface them so a shopper sees availability up front and cannot add an out-of-stock item.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ProductGrid, { isOutOfStock } from '../ProductGrid';
import type { Product } from '../../App';

function product(overrides: Partial<Product> = {}): Product {
  return { sku: 'GAM-1', name: 'Test Laptop', price: 1499, ...overrides };
}

describe('isOutOfStock', () => {
  it('is true when cart_eligible is false', () => {
    expect(isOutOfStock(product({ cart_eligible: false }))).toBe(true);
  });
  it('is true when stock_status is out_of_stock', () => {
    expect(isOutOfStock(product({ stock_status: 'out_of_stock' }))).toBe(true);
  });
  it('is false for an in-stock item', () => {
    expect(isOutOfStock(product({ stock_status: 'in_stock', cart_eligible: true }))).toBe(false);
  });
});

describe('ProductGrid stock badges', () => {
  it('renders an "In stock" badge', () => {
    render(<ProductGrid products={[product({ stock_status: 'in_stock', cart_eligible: true })]} />);
    expect(screen.getByTestId('stock-badge')).toHaveTextContent(/in stock/i);
  });

  it('renders urgency for low stock', () => {
    render(<ProductGrid products={[product({ stock_status: 'very_low_stock', stock_urgency: 'Only 2 left', cart_eligible: true })]} />);
    expect(screen.getByTestId('stock-badge')).toHaveTextContent(/only 2 left/i);
  });

  it('renders no badge when stock_status is unknown (no false signal)', () => {
    render(<ProductGrid products={[product()]} />);
    expect(screen.queryByTestId('stock-badge')).toBeNull();
  });
});

describe('ProductGrid cart gating', () => {
  it('disables Add to Cart and shows "Out of stock" when not cart-eligible', () => {
    const onAdd = vi.fn();
    render(<ProductGrid products={[product({ stock_status: 'out_of_stock', cart_eligible: false })]} onAdd={onAdd} />);
    const btn = screen.getByRole('button', { name: /out of stock/i });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('allows Add to Cart for an in-stock item', () => {
    const onAdd = vi.fn();
    render(<ProductGrid products={[product({ sku: 'GAM-9', stock_status: 'in_stock', cart_eligible: true })]} onAdd={onAdd} />);
    const btn = screen.getByRole('button', { name: /add to cart/i });
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    expect(onAdd).toHaveBeenCalledWith('GAM-9');
  });
});
