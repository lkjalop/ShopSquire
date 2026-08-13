import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import HippographEvidencePanel from '../HippographEvidencePanel';

describe('HippographEvidencePanel', () => {
  it('shows provenance while denying commerce authority', () => {
    render(<HippographEvidencePanel
      insights={[{
        id: 'requirement:ram', label: 'RAM requirement', score: 0.8,
        authority: 'evidence_only',
        source_health: { status: 'degraded', degraded_sources: [{ source: 'publisher', reason: 'stale' }] },
        evidence_path: { nodes: ['case:1', 'requirement:ram'], hops: 1, authority: 'evidence_only', edges: [] },
      }]}
      classNames={{ anchorBlock: 'anchor', sectionTitle: 'title', muted: 'muted', kvRow: 'kv' }}
    />);

    expect(screen.getByTestId('hippograph-evidence-surface')).toHaveTextContent(/cannot authorize a commercial action/i);
    expect(screen.getByText(/case:1 → requirement:ram/)).toBeInTheDocument();
    expect(screen.getByTestId('hippograph-degraded-sources')).toHaveTextContent(/stale/);
  });
});
