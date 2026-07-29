import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DecisionTrace, {
  HippographEvidenceSurface,
  TRACE_SECTIONS,
  type TraceLeafTab,
} from '../DecisionTrace';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderTrace(initialTab: TraceLeafTab = 'summary') {
  return render(
    <DecisionTrace
      traceId={null}
      initialTab={initialTab}
      onClose={() => undefined}
    />,
  );
}

describe('Decision Trace rendered navigation', () => {
  it('keeps every legacy leaf reachable through the five sections', () => {
    renderTrace();

    for (const section of TRACE_SECTIONS) {
      fireEvent.click(screen.getByRole('button', { name: section.label }));
      for (const leaf of section.leaves) {
        const tab = screen.getByTestId(`trace-leaf-${leaf}`);
        expect(tab).toBeVisible();
        fireEvent.click(tab);
        expect(tab).toHaveAttribute('aria-selected', 'true');
        expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', `trace-leaf-${leaf}`);
      }
    }
  });

  it('preserves old leaf deep links including execution', () => {
    for (const section of TRACE_SECTIONS) {
      for (const leaf of section.leaves) {
        const view = renderTrace(leaf);
        expect(screen.getByTestId(`trace-leaf-${leaf}`)).toHaveAttribute('aria-selected', 'true');
        view.unmount();
      }
    }
  });

  it('supports tab keyboard navigation and does not add API calls', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    renderTrace('summary');
    const tablist = screen.getByRole('tablist');

    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    expect(screen.getByTestId('trace-leaf-events')).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(tablist, { key: 'End' });
    expect(screen.getByTestId('trace-leaf-execution')).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(tablist, { key: 'Home' });
    expect(screen.getByTestId('trace-leaf-summary')).toHaveAttribute('aria-selected', 'true');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('renders bounded Hippograph provenance and degraded-source details', () => {
    render(
      <HippographEvidenceSurface
        insights={[{
          id: 'path-1',
          label: 'Component exposure',
          authority: 'evidence_only',
          score: 0.72,
          source_health: {
            status: 'degraded',
            degraded_sources: [{ source: 'public-index', reason: 'stale' }],
          },
          evidence_path: {
            path_id: 'path-1',
            nodes: ['component', 'supplier', 'product'],
            hops: 2,
            edges: [{
              source: 'component',
              target: 'supplier',
              evidence: [{
                evidence_id: 'evidence-1',
                edge_id: 'edge-1',
                observed_at: '2026-07-29T00:00:00Z',
                effective_at: '2026-07-28T00:00:00Z',
                source_authority: 'advisory',
                source_health: 'degraded',
                freshness_weight: 0.6,
              }],
            }],
          },
        }]}
      />,
    );

    expect(screen.getByTestId('hippograph-evidence-surface')).toHaveTextContent('Evidence-only retrieval');
    expect(screen.getByTestId('hippograph-degraded-sources')).toHaveTextContent('public-index (stale)');
    expect(screen.getByText(/evidence evidence-1/)).toHaveTextContent('edge edge-1');
  });
});
