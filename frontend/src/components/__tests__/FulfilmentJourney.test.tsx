/** FulfilmentJourney — buyer-safe bitemporal history (event · state · actor · time, no evidence). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('../../lib/api', () => ({ getFulfillmentJourney: vi.fn() }));
import * as api from '../../lib/api';
import FulfilmentJourney from '../FulfilmentJourney';

beforeEach(() => { vi.clearAllMocks(); });

describe('FulfilmentJourney', () => {
  it('renders the transition steps', async () => {
    (api.getFulfillmentJourney as any).mockResolvedValue({
      journey: [
        { event: 'case_opened', state: 'NEW', actor_type: 'system', valid_from: '2026-06-26 09:00:00' },
        { event: 'buyer_committed', state: 'COMMITTED', actor_type: 'buyer', valid_from: '2026-06-26 09:05:00' },
      ],
    });
    render(<FulfilmentJourney caseId="fc-1" />);
    await waitFor(() => expect(screen.getAllByTestId('fj-event')).toHaveLength(2));
    expect(screen.getByText('buyer_committed')).toBeTruthy();
  });

  it('shows an error without crashing', async () => {
    (api.getFulfillmentJourney as any).mockRejectedValue(new Error('nope'));
    render(<FulfilmentJourney caseId="fc-1" />);
    expect(await screen.findByTestId('fj-error')).toHaveTextContent('nope');
  });
});
