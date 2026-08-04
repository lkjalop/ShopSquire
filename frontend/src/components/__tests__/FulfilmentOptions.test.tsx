/**
 * FulfilmentOptions — the buyer-side procurement UI. Each button maps to one backend transition;
 * here we verify the component renders the right gate and calls the right endpoint (the endpoints
 * themselves are proven by the Python fulfilment suite).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../../lib/api', () => ({
  getFulfillmentCase: vi.fn(),
  commitFulfillmentCase: vi.fn(),
  selectFulfillmentOption: vi.fn(),
}));
import * as api from '../../lib/api';
import FulfilmentOptions from '../FulfilmentOptions';

const CASE = { case_id: 'fc-12345678', status: 'AWAITING_BUYER_COMMITMENT', shortfall: 6, item_ref: 'SKU-1' };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FulfilmentOptions', () => {
  it('GATE 1: shows confirm-sourcing and commits via the buyer endpoint', async () => {
    (api.getFulfillmentCase as any).mockResolvedValue({ state: 'AWAITING_BUYER_COMMITMENT', state_json: {} });
    (api.commitFulfillmentCase as any).mockResolvedValue({ state: 'COMMITTED' });
    render(<FulfilmentOptions caseSummary={CASE} uid="u1" />);
    const btn = await screen.findByTestId('fc-commit-btn');
    expect(screen.getByText(/only contact a supplier after you confirm/i)).toBeTruthy();
    fireEvent.click(btn);
    await waitFor(() => expect(api.commitFulfillmentCase).toHaveBeenCalledWith('fc-12345678', 'u1'));
  });

  it('GATE 1: shows the "why procurement" trace summary from availability', async () => {
    (api.getFulfillmentCase as any).mockResolvedValue({
      state: 'AWAITING_BUYER_COMMITMENT',
      state_json: { availability: { requested_qty: 20, in_stock: 14, shortfall: 6 } },
    });
    render(<FulfilmentOptions caseSummary={CASE} uid="u1" />);
    const why = await screen.findByTestId('fc-why');
    expect(why).toHaveTextContent(/Inventory checked: 14 of 20 in stock/i);
    expect(why).toHaveTextContent(/Shortfall found: 6 unit/i);
    expect(why).toHaveTextContent(/No supplier contacted yet/i);
  });

  it('shows buyer-safe copy while the supplier draft is under human review', async () => {
    (api.getFulfillmentCase as any).mockResolvedValue({
      state: 'QUOTE_DRAFTED',
      state_json: { availability: { requested_qty: 20, in_stock: 14, shortfall: 6 } },
    });
    render(<FulfilmentOptions caseSummary={{ ...CASE, status: 'QUOTE_DRAFTED' }} uid="u1" />);
    const review = await screen.findByTestId('fc-draft-review');
    expect(review).toHaveTextContent(/drafted for human review/i);
    expect(review).toHaveTextContent(/only contacted after the approval gate/i);
  });

  it('renders options with tradeoffs + a deadline flag, and selects the chosen one', async () => {
    (api.getFulfillmentCase as any).mockResolvedValue({
      state: 'OPTIONS_READY',
      state_json: {
        options: [
          { option_id: 'opt-ship_together', option_type: 'ship_together', title: 'Ship all 10 together',
            estimated_delivery_at: '2026-07-08', total_units: 10,
            constraints_satisfied: { complete: true, deadline_met: false, within_budget: true },
            tradeoffs: ['one delivery', 'waits for the supplier units'] },
          { option_id: 'opt-substitute_shortfall', option_type: 'substitute_shortfall', title: 'Use ALT-1 for 6',
            estimated_delivery_at: '2026-07-01', total_units: 10,
            constraints_satisfied: { complete: true, deadline_met: true, within_budget: true },
            tradeoffs: ['complete sooner', 'mixed fleet'] },
        ],
      },
    });
    (api.selectFulfillmentOption as any).mockResolvedValue({ state: 'SELECTED' });
    render(<FulfilmentOptions caseSummary={{ ...CASE, status: 'OPTIONS_READY' }} uid="u1" />);

    await screen.findByTestId('fc-options');
    expect(screen.getByTestId('fc-option-ship_together')).toBeTruthy();
    expect(screen.getByTestId('fc-flag-deadline')).toHaveTextContent(/may miss deadline/i);

    // pick the substitute then confirm
    fireEvent.click(screen.getByDisplayValue('opt-substitute_shortfall'));
    fireEvent.click(screen.getByTestId('fc-select-btn'));
    await waitFor(() =>
      expect(api.selectFulfillmentOption).toHaveBeenCalledWith('fc-12345678', 'u1', 'opt-substitute_shortfall'));
  });

  it('surfaces an error without crashing', async () => {
    (api.getFulfillmentCase as any).mockRejectedValue(new Error('boom'));
    render(<FulfilmentOptions caseSummary={CASE} uid="u1" />);
    expect(await screen.findByTestId('fc-error')).toHaveTextContent('boom');
  });

  it('shows the final order confirmation with the PO reference once completed', async () => {
    (api.getFulfillmentCase as any).mockResolvedValue({
      state: 'COMPLETED',
      state_json: { purchase_order: { po_ref: 'PO-AB12CD34EF', status: 'created', quantity: 6 } },
    });
    render(<FulfilmentOptions caseSummary={{ ...CASE, status: 'COMPLETED' }} uid="u1" />);
    const confirmed = await screen.findByTestId('fc-confirmed');
    expect(confirmed).toHaveTextContent(/order confirmed/i);
    expect(confirmed).toHaveTextContent(/PO-AB12CD34EF/);
  });
});
