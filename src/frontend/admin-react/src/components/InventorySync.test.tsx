import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fetchInventoryConnectorSummary,
  fetchInventoryExternalStock,
  fetchInventoryProjectionStatus,
  fetchInventorySyncRuns,
  rebuildInventoryProjection,
} from '../api';
import { InventorySync } from './InventorySync';

vi.mock('../api', () => ({
  fetchInventoryConnectorSummary: vi.fn(),
  fetchInventoryExternalStock: vi.fn(),
  fetchInventoryProjectionStatus: vi.fn(),
  fetchInventorySyncRuns: vi.fn(),
  rebuildInventoryProjection: vi.fn(),
  runInventorySync: vi.fn(),
}));

describe('InventorySync governed projection', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(fetchInventoryConnectorSummary).mockResolvedValue({
      items: [{ id: 'csv', name: 'CSV', health: { ok: true } }],
    });
    vi.mocked(fetchInventorySyncRuns).mockResolvedValue({ items: [] });
    vi.mocked(fetchInventoryExternalStock).mockResolvedValue({ items: [] });
    vi.mocked(fetchInventoryProjectionStatus).mockResolvedValue({
      tenant_id: 'tenant-a',
      source: null,
      runs: [{
        id: 'run-1',
        source: 'csv',
        projection_version: 1,
        input_count: 12,
        projection_hash: 'abcdef1234567890',
        status: 'quarantined',
        started_at: '2026-07-29T00:00:00Z',
        finished_at: '2026-07-29T00:00:01Z',
      }],
      exceptions: [{
        id: 'exception-1',
        source: 'csv',
        projection_run_id: 'run-1',
        exception_type: 'atp_reconciliation',
        details: { expected: 10, projected: 8 },
        created_at: '2026-07-29T00:00:01Z',
      }],
      balance_summary: [{ source: 'csv', status: 'available', row_count: 4 }],
      execution_policy: {
        ready_required: true,
        quarantined_projection_can_execute: false,
        hidden_compensation_allowed: false,
      },
    });
    vi.mocked(rebuildInventoryProjection).mockResolvedValue({
      run_id: 'run-2',
      source: 'csv',
      status: 'insufficient',
      projection_hash: '1234',
      input_count: 0,
      balance_count: 0,
      exception_count: 1,
      execution_allowed: false,
    });
  });

  it('shows quarantine evidence and never hides compensation', async () => {
    render(<InventorySync role="owner" />);

    const projection = await screen.findByTestId('inventory-projection-status');
    expect(projection).toHaveTextContent('Latest: QUARANTINED');
    expect(projection).toHaveTextContent('Hidden compensation: prohibited');
    expect(projection).toHaveTextContent('atp reconciliation');

    fireEvent.click(screen.getByRole('button', { name: 'Rebuild governed projection' }));
    await waitFor(() => expect(rebuildInventoryProjection).toHaveBeenCalledWith('csv'));
    expect(await screen.findByText(/Projection: insufficient/)).toBeInTheDocument();
  });
});
