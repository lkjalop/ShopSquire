/**
 * FulfilmentTraceLink — resolves a procurement case from the decision trace_id and renders its journey.
 * A no-op when no case was opened for the turn (the common path).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('../../lib/api', () => ({
  getFulfillmentCaseByTrace: vi.fn(),
  getFulfillmentJourney: vi.fn(),
}));
import * as api from '../../lib/api';
import FulfilmentTraceLink from '../FulfilmentTraceLink';

beforeEach(() => { vi.clearAllMocks(); });

describe('FulfilmentTraceLink', () => {
  it('renders the journey when a case is linked to the trace', async () => {
    (api.getFulfillmentCaseByTrace as any).mockResolvedValue({ case_id: 'fc-abcdef12' });
    (api.getFulfillmentJourney as any).mockResolvedValue({
      journey: [{ event: 'case_opened', state: 'NEW', actor_type: 'agent', valid_from: '2026-06-27' }],
    });
    render(<FulfilmentTraceLink traceId="T-LINK-1" />);
    await screen.findByTestId('trace-fulfilment-link');
    expect(screen.getByText(/Procurement journey for this decision/i)).toBeTruthy();
    await waitFor(() => expect(api.getFulfillmentJourney).toHaveBeenCalledWith('fc-abcdef12'));
  });

  it('renders nothing when no case is linked (404 → null)', async () => {
    (api.getFulfillmentCaseByTrace as any).mockResolvedValue(null);
    const { container } = render(<FulfilmentTraceLink traceId="T-NONE" />);
    await waitFor(() => expect(api.getFulfillmentCaseByTrace).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="trace-fulfilment-link"]')).toBeNull();
  });

  it('renders nothing without a traceId', () => {
    const { container } = render(<FulfilmentTraceLink />);
    expect(container.firstChild).toBeNull();
    expect(api.getFulfillmentCaseByTrace).not.toHaveBeenCalled();
  });
});
