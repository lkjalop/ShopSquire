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
  it('docks on desktop by default and can return to a floating panel', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
    renderTrace();

    const dialog = screen.getByTestId('decision-trace-modal');
    expect(dialog.className).toContain('docked');
    fireEvent.click(screen.getByRole('button', { name: 'Float trace panel' }));
    expect(dialog.className).not.toContain('docked');
    expect(screen.getByRole('button', { name: 'Dock trace panel on the right' })).toBeVisible();
  });

  it('keeps every legacy leaf reachable through the five sections', () => {
    renderTrace();

    for (const section of TRACE_SECTIONS) {
      if (section.id === 'audit-technical') {
        fireEvent.click(screen.getByRole('button', { name: /Advanced technical details/i }));
      } else {
        fireEvent.click(screen.getByRole('button', { name: new RegExp(section.label) }));
      }
      const reveal = screen.queryByRole('button', { name: /Show empty panels/i });
      if (reveal) fireEvent.click(reveal);
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

  it('keeps trust cues persistent while progressively disclosing specialist panels', () => {
    renderTrace('summary');
    expect(screen.getByTestId('trace-trust-strip')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: /Evidence & Risk/i }));
    expect(screen.getByTestId('trace-leaf-evidence')).not.toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /Show empty panels/i }));
    expect(screen.getByTestId('trace-leaf-evidence')).toBeVisible();
  });

  it('places audit and raw behind an advanced disclosure and exposes mobile section navigation', () => {
    renderTrace('summary');
    expect(screen.getByTestId('trace-leaf-audit')).not.toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /Advanced technical details/i }));
    expect(screen.getByTestId('trace-leaf-audit')).toBeVisible();
    expect(screen.getByLabelText('Decision Trace section')).toBeInTheDocument();
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
