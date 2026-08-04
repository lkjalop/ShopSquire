import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import CreateFromOrder from './CreateFromOrder';

vi.mock('../../api', () => ({ fcFromOrder: vi.fn() }));
import { fcFromOrder } from '../../api';

describe('CreateFromOrder', () => {
  beforeEach(() => vi.clearAllMocks());

  it('plans + creates grouped cases and shows them by supplier', async () => {
    (fcFromOrder as any).mockResolvedValue({
      order_group_id: 'order-abc123',
      case_count: 2,
      cases: [
        { case_id: 'c1aaaaaa', supplier_name: 'CreatorFleet Wholesale', lines: [{ item_ref: 'GAM-0002', quantity: 7 }], total_quantity: 7 },
        { case_id: 'c2bbbbbb', supplier_name: 'PeriLink Accessories', lines: [{ item_ref: 'MON-1', quantity: 10 }, { item_ref: 'AUD-1', quantity: 5 }], total_quantity: 15 },
      ],
    });
    const onCreated = vi.fn();
    render(<CreateFromOrder onCreated={onCreated} />);
    fireEvent.change(screen.getByTestId('cfo-input'), { target: { value: '15 laptops + 10 monitors + 5 headsets' } });
    fireEvent.click(screen.getByTestId('cfo-run'));

    await waitFor(() => expect(screen.getByTestId('cfo-result')).toBeInTheDocument());
    expect(fcFromOrder).toHaveBeenCalledWith('15 laptops + 10 monitors + 5 headsets');
    expect(screen.getByText(/Created 2 cases/)).toBeInTheDocument();
    expect(screen.getByText('CreatorFleet Wholesale')).toBeInTheDocument();
    expect(screen.getByText('PeriLink Accessories')).toBeInTheDocument();
    expect(onCreated).toHaveBeenCalled();
  });

  it('shows an error when creation fails', async () => {
    (fcFromOrder as any).mockRejectedValue(new Error('no_order_lines_resolved'));
    render(<CreateFromOrder />);
    fireEvent.change(screen.getByTestId('cfo-input'), { target: { value: 'nonsense' } });
    fireEvent.click(screen.getByTestId('cfo-run'));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('no_order_lines_resolved'));
  });
});
