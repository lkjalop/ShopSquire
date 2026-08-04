import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CaseQueue from './CaseQueue';
import type { FulfillmentCaseRow } from '../../api';

function row(over: Partial<FulfillmentCaseRow>): FulfillmentCaseRow {
  return {
    case_id: 'case-00000001',
    status: 'committed',
    item_ref: 'SKU-1',
    quantity: 10,
    requested_by: 'buyer@corp.example',
    source_trace_id: 'trace-1',
    updated_at: '2026-06-27 10:00',
    ...over,
  } as FulfillmentCaseRow;
}

const CASES: FulfillmentCaseRow[] = [
  row({ case_id: 'aaaa1111', status: 'committed', item_ref: 'LAP-1', updated_at: '2026-06-27 09:00' }),
  row({ case_id: 'bbbb2222', status: 'completed', item_ref: 'LAP-2', updated_at: '2026-06-27 12:00' }),
  row({ case_id: 'cccc3333', status: 'no_approved_supplier', item_ref: 'LAP-3', updated_at: '2026-06-27 11:00' }),
];

describe('CaseQueue', () => {
  it('defaults to the "needs action" view, hiding terminal (completed) cases', () => {
    render(<CaseQueue cases={CASES} sel="" onSelect={vi.fn()} onRefresh={vi.fn()} />);
    const rows = screen.getAllByTestId('op-queue-row');
    // committed + no_approved_supplier are needs-action; completed is not
    expect(rows).toHaveLength(2);
    expect(screen.getByTestId('op-queue-count')).toHaveTextContent('2 of 3');
    expect(screen.queryByText('bbbb2222'.slice(0, 8))).toBeNull();
  });

  it('shows every case under the "all" chip, newest-first', () => {
    render(<CaseQueue cases={CASES} sel="" onSelect={vi.fn()} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByTestId('op-chip-all'));
    const rows = screen.getAllByTestId('op-queue-row');
    expect(rows).toHaveLength(3);
    // newest updated_at (12:00 -> bbbb2222) must be first
    expect(within(rows[0]).getByText('bbbb2222'.slice(0, 8))).toBeInTheDocument();
  });

  it('filters by the search term across id / status / sku', () => {
    render(<CaseQueue cases={CASES} sel="" onSelect={vi.fn()} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByTestId('op-chip-all'));
    fireEvent.change(screen.getByTestId('op-queue-search'), { target: { value: 'lap-3' } });
    const rows = screen.getAllByTestId('op-queue-row');
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).getByText('cccc3333'.slice(0, 8))).toBeInTheDocument();
  });

  it('warns about blocked (no approved supplier) cases and badges the row', () => {
    render(<CaseQueue cases={CASES} sel="" onSelect={vi.fn()} onRefresh={vi.fn()} />);
    expect(screen.getByTestId('op-queue-blocked-warning')).toHaveTextContent(/1 case blocked/i);
    expect(screen.getByTestId('op-queue-row-blocked')).toBeInTheDocument();
  });

  it('calls onSelect with the case id when a row is clicked', () => {
    const onSelect = vi.fn();
    render(<CaseQueue cases={CASES} sel="" onSelect={onSelect} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getAllByTestId('op-queue-row')[0]);
    expect(onSelect).toHaveBeenCalledWith(expect.any(String));
  });
});
