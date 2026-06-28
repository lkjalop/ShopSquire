import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import AutonomyAudit from './AutonomyAudit';
import type { AutonomousAudit } from '../../api';

vi.mock('../../api', () => ({ fcAutonomousAudit: vi.fn() }));
import { fcAutonomousAudit } from '../../api';

const base: AutonomousAudit = {
  rows: [
    { action_type: 'supplier_rfq_send', decision: 'allow', reason: 'autonomous_send', confidence: 0.95, target: 'FC-12345678', created_at: '2026-06-28 10:00:00' },
    { action_type: 'supplier_rfq_send', decision: 'escalate', reason: 'low_confidence', confidence: 0.5, target: 'FC-9', created_at: '2026-06-28 09:59:00' },
  ],
  summary: { sent: 1, escalated: 1, by_reason: { low_confidence: 1 } },
  enabled: true, killed: false,
  transport: { mode: 'sandbox', configured: true, missing: [], transmits: false },
};

describe('AutonomyAudit', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows the live toggle state, summary, and the decision rows', async () => {
    (fcAutonomousAudit as any).mockResolvedValue(base);
    render(<AutonomyAudit />);
    await waitFor(() => expect(screen.getByTestId('autonomy-audit')).toBeInTheDocument());
    expect(screen.getByText('AUTONOMY ON')).toBeInTheDocument();
    expect(screen.getByTestId('autonomy-sent')).toHaveTextContent('1');
    expect(screen.getByTestId('autonomy-escalated')).toHaveTextContent('1');
    expect(screen.getByText(/low_confidence \(1\)/)).toBeInTheDocument();
    expect(screen.getByText('sent')).toBeInTheDocument();        // decision 'allow' rendered as 'sent'
    expect(screen.getByText('escalate')).toBeInTheDocument();
  });

  it('warns when SMTP is selected but not configured', async () => {
    (fcAutonomousAudit as any).mockResolvedValue({
      ...base, transport: { mode: 'smtp', configured: false, missing: ['SMTP_HOST'], transmits: true } });
    render(<AutonomyAudit />);
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('alert')).toHaveTextContent('SMTP_HOST');
  });

  it('shows the kill-switch badge when killed', async () => {
    (fcAutonomousAudit as any).mockResolvedValue({ ...base, killed: true });
    render(<AutonomyAudit />);
    await waitFor(() => expect(screen.getByText('KILL SWITCH')).toBeInTheDocument());
  });
});
