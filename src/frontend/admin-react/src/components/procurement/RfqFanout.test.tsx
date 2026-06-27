import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import RfqFanout from './RfqFanout';
import type { RfqFanoutDraft } from '../../api';

const DRAFTS: RfqFanoutDraft[] = [
  { recipient_ref: 'A', recipient_domain: 'a.example', recipient_email: 'rfq@a.example', subject: 'RFQ for SKU-1',
    body: '...', confidence: 0.9, content_hash: 'h1', send_gate: { decision: 'allow', reasons: [] } },
  { recipient_ref: 'B', recipient_domain: 'b.example', recipient_email: null, subject: 'RFQ for SKU-1',
    body: '...', confidence: 0.7, content_hash: 'h2', send_gate: { decision: 'needs_info', reasons: ['low_confidence'] } },
];

describe('RfqFanout', () => {
  it('renders nothing without drafts', () => {
    const { container } = render(<RfqFanout drafts={[]} onCompare={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('previews a caged draft per supplier with its send-gate', () => {
    render(<RfqFanout drafts={DRAFTS} onCompare={vi.fn()} />);
    const previews = screen.getAllByTestId('op-rfq-draft');
    expect(previews).toHaveLength(2);
    expect(within(previews[0]).getByText('a.example')).toBeInTheDocument();
    const gates = screen.getAllByTestId('op-rfq-gate').map((n) => n.textContent);
    expect(gates.join(' ')).toMatch(/allow/);
    expect(gates.join(' ')).toMatch(/needs_info/);
  });

  it('collects entered quotes, calls onCompare, and highlights the recommended supplier', async () => {
    const onCompare = vi.fn().mockResolvedValue({
      considered: 2, excluded: 0, recommended: { recipient_domain: 'b.example', composite: 0.95 },
      ranked: [
        { recipient_domain: 'b.example', unit_price_cents: 100000, lead_time_days: 7, reliability: 0.9, composite: 0.95, scores: { price: 1, lead_time: 1, reliability: 0.9 }, reasons: ['lowest_unit_price'] },
        { recipient_domain: 'a.example', unit_price_cents: 120000, lead_time_days: 10, reliability: 0.95, composite: 0.82, scores: { price: 0.83, lead_time: 0.7, reliability: 0.95 }, reasons: [] },
      ],
    });
    render(<RfqFanout drafts={DRAFTS} onCompare={onCompare} />);
    const rows = screen.getAllByTestId('op-rfq-quote-row');
    fireEvent.change(within(rows[0]).getByTestId('op-rfq-price'), { target: { value: '120000' } });
    fireEvent.change(within(rows[1]).getByTestId('op-rfq-price'), { target: { value: '100000' } });
    fireEvent.click(screen.getByTestId('op-rfq-compare'));

    await waitFor(() => expect(onCompare).toHaveBeenCalledTimes(1));
    // both priced rows submitted
    expect(onCompare.mock.calls[0][0]).toHaveLength(2);
    await waitFor(() => expect(screen.getByTestId('op-rfq-result')).toBeInTheDocument());
    expect(screen.getAllByTestId('op-rfq-ranked')).toHaveLength(2);
    const rec = screen.getByTestId('op-rfq-recommended').closest('[data-testid="op-rfq-ranked"]');
    expect(rec).toHaveTextContent('b.example');
  });

  it('omits rows with no price from the compare payload', async () => {
    const onCompare = vi.fn().mockResolvedValue({ considered: 1, excluded: 0, recommended: null, ranked: [] });
    render(<RfqFanout drafts={DRAFTS} onCompare={onCompare} />);
    const rows = screen.getAllByTestId('op-rfq-quote-row');
    fireEvent.change(within(rows[0]).getByTestId('op-rfq-price'), { target: { value: '120000' } });
    // row[1] left blank
    fireEvent.click(screen.getByTestId('op-rfq-compare'));
    await waitFor(() => expect(onCompare).toHaveBeenCalled());
    expect(onCompare.mock.calls[0][0]).toHaveLength(1);
    expect(onCompare.mock.calls[0][0][0].recipient_domain).toBe('a.example');
  });
});
