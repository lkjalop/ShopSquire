import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ImageRecommendPanel from '../ImageRecommendPanel';

describe('ImageRecommendPanel canonical slate', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  it('renders the shared slate without issuing an independent suggest request', async () => {
    render(
      <ImageRecommendPanel
        imageContexts={[{
          labels: ['laptop'],
          ocr_text: '',
          cv_signals: {},
          source_name: 'office-laptop.jpg',
        }]}
        userQuery="a work laptop under 1900"
        canonicalProducts={[{
          sku: 'LAP-CANONICAL',
          name: 'Canonical ThinkPad',
          price: 1599,
          why: ['Within budget', 'Office workload fit'],
        }]}
        canonicalSummary="One recommendation turn produced this slate."
      />,
    );

    expect(await screen.findByText(/Canonical ThinkPad/i)).toBeInTheDocument();
    expect(screen.getByText(/One recommendation turn produced this slate/i)).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
  });

  it('keeps a pending shared turn pending instead of falling back to local products', () => {
    render(
      <ImageRecommendPanel
        imageContexts={[]}
        userQuery="find something like this"
        canonicalProducts={null}
      />,
    );

    expect(screen.getByText(/Finding the best matches/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
