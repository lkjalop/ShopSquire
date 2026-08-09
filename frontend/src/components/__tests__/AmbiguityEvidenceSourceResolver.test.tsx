import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import AmbiguityExplorationPanel from '../AmbiguityExplorationPanel';

const exploration = {
  schema_version: 'ambiguity-exploration-v1' as const,
  retained_purpose: 'PLC factory and OT cyber range',
  status: 'provisional' as const,
  interpretations: [], execution: 'local_exploration_completed',
  evidence: 'material_gaps', decision: 'exploration_allowed', cart_authority: 'none',
  provider_accounting: { external_calls: 0, paid_calls: 0 },
};

describe('buyer evidence source resolver', () => {
  it('checks locally before offering an explicitly authorized canonical fetch', async () => {
    const resolve = vi.fn().mockResolvedValue({
      status: 'resolved', reason: 'reviewed_source_matched',
      candidates: [{
        source_id: 'factory_io_official_docs', publisher: 'Real Games',
        canonical_url: 'https://docs.factoryio.com/manual/system-requirements/',
      }],
    });
    render(<AmbiguityExplorationPanel
      exploration={exploration}
      onResearch={() => undefined} onUpload={() => undefined}
      onEnterSpecifications={() => undefined} onResolveEvidenceSource={resolve}
    />);
    fireEvent.click(screen.getByRole('button', { name: 'Use official link or vendor' }));
    fireEvent.change(screen.getByLabelText('Official requirements URL or named vendor'), {
      target: { value: 'https://docs.factoryio.com/manual/system-requirements/' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Check source' }));
    await waitFor(() => expect(resolve).toHaveBeenCalledWith({
      source_url: 'https://docs.factoryio.com/manual/system-requirements/',
    }, false));
    expect(await screen.findByText(/reviewed source matched/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Research matched canonical source' }));
    await waitFor(() => expect(resolve).toHaveBeenLastCalledWith({
      source_url: 'https://docs.factoryio.com/manual/system-requirements/',
    }, true));
  });

  it('keeps an ambiguous vendor as a choice instead of dispatching research', async () => {
    const resolve = vi.fn().mockResolvedValue({
      status: 'ambiguous', reason: 'multiple_enrolled_sources_match',
      candidates: [
        { source_id: 'autocad', publisher: 'Autodesk', canonical_url: 'https://www.autodesk.com/autocad' },
        { source_id: 'revit', publisher: 'Autodesk', canonical_url: 'https://www.autodesk.com/revit' },
      ],
    });
    render(<AmbiguityExplorationPanel
      exploration={exploration}
      onResearch={() => undefined} onUpload={() => undefined}
      onEnterSpecifications={() => undefined} onResolveEvidenceSource={resolve}
    />);
    fireEvent.click(screen.getByRole('button', { name: 'Use official link or vendor' }));
    fireEvent.change(screen.getByLabelText('Official requirements URL or named vendor'), {
      target: { value: 'Autodesk' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Check source' }));
    expect(await screen.findByText(/multiple enrolled sources match/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Research matched canonical source' })).toBeNull();
    expect(resolve).toHaveBeenCalledTimes(1);
  });
});
