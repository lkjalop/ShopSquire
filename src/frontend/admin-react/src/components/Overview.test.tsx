import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Overview } from './Overview';
import {
  fetchComplianceLiveFeed,
  fetchDemoReadiness,
  fetchLiveFeed,
  fetchOverview,
  fetchPersonaSuccess,
} from '../api';

vi.mock('../api', () => ({
  fetchOverview: vi.fn(),
  fetchLiveFeed: vi.fn(),
  fetchComplianceLiveFeed: vi.fn(),
  fetchDemoReadiness: vi.fn(),
  fetchPersonaSuccess: vi.fn(),
}));

const overview = {
  revenue_today: 0,
  orders_today: 0,
  autonomy_percent: 0,
  security_status: 'unknown',
  critical_events_24h: 0,
  approval_pending: 0,
  decision_series: [],
  approval_latency_p95_sec: 0,
  policy_reject_rate: 0,
  uptime_seconds: 0,
};

describe('Overview evidence states', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(fetchOverview).mockResolvedValue(overview);
    vi.mocked(fetchLiveFeed).mockResolvedValue({ items: [] });
    vi.mocked(fetchComplianceLiveFeed).mockResolvedValue({ items: [] } as any);
    vi.mocked(fetchPersonaSuccess).mockResolvedValue({ personas: [] } as any);
  });

  it('does not render invented success ratios and distinguishes disabled evidence from zero', async () => {
    vi.mocked(fetchDemoReadiness).mockRejectedValue(Object.assign(new Error('disabled'), { status: 404 }));
    render(<Overview role="merchant" />);

    expect(await screen.findByTestId('revenue-comparison-status')).toHaveTextContent('No revenue recorded today');
    expect(screen.getByTestId('order-approval-status')).toHaveTextContent('No orders recorded today');
    expect(screen.queryByText('+12.3% WoW')).not.toBeInTheDocument();
    expect(screen.queryByText('95.4% approved')).not.toBeInTheDocument();
    expect(await screen.findByTestId('demo-readiness-status')).toHaveTextContent('disabled');

    const blockedRow = screen.getByText('Blocked attacks').closest('.list-item');
    expect(blockedRow).not.toBeNull();
    expect(within(blockedRow as HTMLElement).getByText('Disabled')).toBeInTheDocument();
  });

  it('preserves a measured zero when readiness evidence is available', async () => {
    vi.mocked(fetchDemoReadiness).mockResolvedValue({
      window_hours: 24,
      security_posture: {
        blocked_attacks: 0, escalations: 0, supplier_quarantines: 0, api_abuse_blocked: 0,
      },
      model_quality: {
        ctr: 0, add_to_cart_rate: 0, low_confidence_fallback_rate: 0,
        low_confidence_count: 0, total_decisions: 0,
      },
    });
    render(<Overview role="merchant" />);

    await waitFor(() => expect(fetchDemoReadiness).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId('demo-readiness-status')).not.toBeInTheDocument());
    const blockedRow = screen.getByText('Blocked attacks').closest('.list-item');
    expect(within(blockedRow as HTMLElement).getByText('0')).toBeInTheDocument();
    const ctrRow = screen.getByText('Upsell CTR').closest('.list-item');
    expect(within(ctrRow as HTMLElement).getByText('0.0%')).toBeInTheDocument();
  });
});
