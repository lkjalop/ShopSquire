/**
 * MultiIntentCard — the buyer confirmation surface for the P0 multi-intent planner. Renders the qty
 * amendment (Confirm qty) + scoped new-category picks (Add), and calls back on each — nothing auto-applies.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import MultiIntentCard from '../MultiIntentCard';
import type { MultiIntentPlan } from '../../lib/api';

const PLAN: MultiIntentPlan = {
  plan: [
    { scope: 'prior', ref: 'LAP-1', name: 'Asus VivoBook', requested_qty: 15, amended: true },
    { scope: 'new', category: 'headsets', budget_max: 1200, results: [
      { sku: 'AUD-1', name: 'RIG Headset', price: 179 },
      { sku: 'AUD-2', name: 'Studio Pro', price: 249 },
    ] },
    { scope: 'new', category: 'hard drives', budget_max: 1200, results: [] },
  ],
  verdict: { ok: true, violations: [] },
  needs_confirmation: true,
  objection_angle: 'value',
};

describe('MultiIntentCard', () => {
  it('confirms the qty amendment via onAmendQty (never auto-applies)', () => {
    const onAmendQty = vi.fn();
    render(<MultiIntentCard plan={PLAN} onAmendQty={onAmendQty} onAddItem={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText(/Asus VivoBook/)).toBeTruthy();
    fireEvent.click(screen.getByText('Confirm qty'));
    expect(onAmendQty).toHaveBeenCalledWith('LAP-1', 15);
  });

  it('adds a scoped pick via onAddItem and shows the value reframe', () => {
    const onAddItem = vi.fn();
    render(<MultiIntentCard plan={PLAN} onAmendQty={vi.fn()} onAddItem={onAddItem} onDismiss={vi.fn()} />);
    expect(screen.getByTestId('multi-intent-objection')).toBeTruthy();      // value reframe note
    expect(screen.getByText(/RIG Headset/)).toBeTruthy();
    fireEvent.click(screen.getAllByText('Add')[0]);
    expect(onAddItem).toHaveBeenCalledWith('AUD-1', 1);
  });

  it('shows a no-options message for a scoped line with no picks', () => {
    render(<MultiIntentCard plan={PLAN} onAmendQty={vi.fn()} onAddItem={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText(/No in-budget options found/)).toBeTruthy();
  });

  it('renders nothing when there is nothing actionable', () => {
    const { container } = render(
      <MultiIntentCard plan={{ plan: [] }} onAmendQty={vi.fn()} onAddItem={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(container.querySelector('[data-testid="multi-intent-card"]')).toBeNull();
  });

  it('does NOT show a Confirm-qty row for a carried-forward (unamended) prior line', () => {
    // a prior line the turn did not change (amended !== true) must never render a spurious amendment
    const plan: MultiIntentPlan = {
      plan: [
        { scope: 'prior', ref: 'LAP-1', name: 'Asus VivoBook', requested_qty: 1, amended: false },
        { scope: 'new', category: 'headsets', budget_max: 1200, results: [{ sku: 'AUD-1', name: 'RIG', price: 179 }] },
      ],
    };
    render(<MultiIntentCard plan={plan} onAmendQty={vi.fn()} onAddItem={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.queryByText('Confirm qty')).toBeNull();          // no spurious amendment
    expect(screen.getByText(/RIG/)).toBeTruthy();                   // but the scoped new line still shows
  });
});
