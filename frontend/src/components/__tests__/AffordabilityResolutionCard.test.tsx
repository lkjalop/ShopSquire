import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import AffordabilityResolutionCard, {
  type AffordabilityResolution,
} from '../AffordabilityResolutionCard';

const resolution: AffordabilityResolution = {
  kind: 'total_budget_exceeded',
  sku: 'LAP-PRO',
  product_name: 'Creator Workstation',
  currency: 'AUD',
  requested_quantity: 20,
  max_affordable_quantity: 15,
  current_unit_price_cents: 350_000,
  cheaper_unit_price_max_cents: 270_000,
  budget_max_cents: 5_400_000,
  proposed_total_cents: 7_000_000,
  other_lines_total_cents: 0,
  choices: ['reduce_quantity', 'increase_budget', 'choose_cheaper_product'],
  requires_confirmation: true,
};

describe('AffordabilityResolutionCard', () => {
  it('shows three explicit choices and never applies one without a click', () => {
    const onChoose = vi.fn();
    render(<AffordabilityResolutionCard resolution={resolution} onChoose={onChoose} />);

    expect(screen.getByText(/Nothing changed/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reduce to 15' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Increase budget/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Choose a cheaper product' })).toBeInTheDocument();
    expect(onChoose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Reduce to 15' }));
    expect(onChoose).toHaveBeenCalledWith('reduce_quantity');
  });
});
