import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';

import OffCatalogSourcingCard from '../OffCatalogSourcingCard';


describe('OffCatalogSourcingCard', () => {
  it('requires an explicit click and reports a draft with no supplier contact', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      case_id: 'fc-123', state: 'COMMITTED', idempotent: false,
      shopping_case_id: 'sc-1', case_revision: 2, supplier_contacted: false,
      draft: {
        status: 'internal_sourcing_brief',
        requires_operator_supplier_resolution: true,
        rfq_preview_path: '/api/v1/fulfillment/cases/fc-123/rfq-fanout',
      },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));

    render(<OffCatalogSourcingCard uid="buyer-1" offer={{
      shopping_case_id: 'sc-1', case_revision: 2, trace_id: 'trace-1',
      label: 'ERP licence', quantity: 200,
    }} />);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/will not contact a supplier/i)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('create-sourcing-request'));
    await waitFor(() => expect(screen.getByTestId('off-catalog-sourcing-created')).toHaveTextContent('fc-123'));
    expect(screen.getByTestId('off-catalog-sourcing-created')).toHaveTextContent(/No supplier has been contacted/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockRestore();
  });
});
