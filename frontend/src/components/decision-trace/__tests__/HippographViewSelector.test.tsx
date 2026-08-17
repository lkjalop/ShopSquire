import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import HippographViewSelector from '../HippographViewSelector';

describe('HippographViewSelector', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('loads the selected purpose and renders only evidence authority', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        receipt: {
          selected_edge_ids: ['edge-1'], visited_node_ids: ['case', 'offer'],
          not_yet_known_edge_ids: ['later'], known_future_edge_ids: [],
          authority: 'evidence_recall_only',
        },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<HippographViewSelector active caseId="case-1" apiKey="operator-key" />);

    fireEvent.click(screen.getByRole('button', { name: 'Who can fulfil this?' }));
    await waitFor(() => expect(screen.getByTestId('hippograph-view-receipt')).toBeInTheDocument());
    expect(fetchMock.mock.calls[0][0]).toContain('purpose=supplier_fulfilment');
    expect(fetchMock.mock.calls[0][0]).toContain('seed_id=shopping_case%3Acase-1');
    expect(screen.getByTestId('hippograph-view-receipt')).toHaveTextContent('evidence_recall_only');
    expect(screen.getByTestId('hippograph-view-receipt')).toHaveTextContent('Known later, excluded: 1');
  });
});
