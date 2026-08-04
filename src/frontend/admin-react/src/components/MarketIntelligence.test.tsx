import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MarketIntelligence } from './MarketIntelligence';
import {
  experimentState,
  fetchExecutiveMetrics,
  governancePulse,
  replayState,
  supportResponse,
} from '../api';

vi.mock('../api', () => ({
  experimentEvaluate: vi.fn(),
  experimentPromote: vi.fn(),
  experimentRevert: vi.fn(),
  experimentState: vi.fn(),
  fetchExecutiveMetrics: vi.fn(),
  governancePulse: vi.fn(),
  marketDigest: vi.fn(),
  marketState: vi.fn(),
  refreshMarket: vi.fn(),
  replayAdvance: vi.fn(),
  replayReset: vi.fn(),
  replayState: vi.fn(),
  supportResponse: vi.fn(),
}));

describe('MarketIntelligence trust labels', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(replayState).mockResolvedValue({
      signals: 3,
      active_findings: 1,
      findings: [],
      label: 'SYNTHETIC REPLAY',
      series: {
        demand: [10, 12],
        conversion: [8, 7],
        dates: ['2026-07-27', '2026-07-28'],
      },
    });
    vi.mocked(experimentState).mockResolvedValue({
      experiment_id: 'ranking',
      status: 'reverted',
      live: false,
      assignments: {},
      last_decision: null,
      last_uplift_pct: null,
      adaptation_killed: false,
    });
    vi.mocked(fetchExecutiveMetrics).mockResolvedValue({
      tenant_id: 'replay-demo',
      data_quality: { event_count: 2 },
      estimates: {},
      actions: [],
      metrics: [{
        metric: 'weeks_of_supply',
        tenant_id: 'replay-demo',
        subject_type: 'sku',
        subject_id: 'SKU-1',
        value: 2,
        unit: 'weeks',
        as_of: '2026-07-28T00:00:00Z',
        status: 'simulated',
        confidence: 0.6,
        coverage: 0.8,
        source_count: 2,
        source_records: [],
        provenance_chain: ['synthetic-replay'],
        definition_version: 'v1',
        visibility: 'operator',
        metadata: {},
      }],
    });
    vi.mocked(governancePulse).mockRejectedValue(new Error('not configured'));
    vi.mocked(supportResponse).mockRejectedValue(new Error('not configured'));
  });

  it('shows synthetic, shadow and freshness labels and separates coverage from confidence', async () => {
    render(<MarketIntelligence />);

    const labels = await screen.findByTestId('mi-trust-labels');
    expect(labels).toHaveTextContent('Evidence: SYNTHETIC');
    expect(labels).toHaveTextContent('Adaptation authority: SHADOW / NOT LIVE');
    expect(labels).toHaveTextContent('Freshness: data through 2026-07-28');
    expect(await screen.findByText(/80% coverage/)).toHaveTextContent('60% confidence');
    expect(screen.getByText('simulated')).toBeInTheDocument();
  });
});
