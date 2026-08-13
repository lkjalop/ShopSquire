import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ProcurementAuditPanel from '../ProcurementAuditPanel';
import ProcurementEventTable from '../ProcurementEventTable';

const classes = { table: 'table', mono: 'mono', kvRow: 'kv' };

describe('procurement presentation boundaries', () => {
  it('keeps event details and raw evidence behind an explicit drill-down', () => {
    render(<ProcurementEventTable
      events={[{
        id: 'e1', event_type: 'supplier_responses_normalized', source_id: 'supplier_stage',
        created_at: '2026-08-13T01:02:03Z',
        payload: { execution: 'deterministic', shortfall: 18, channel: 'email', secret: 'recorded' },
      }]}
      classNames={classes}
      componentSource={() => 'Supplier stage'}
      displayEventType={() => 'Supplier responses normalized'}
      eventSummary={() => 'fallback'}
    />);
    expect(screen.getByText(/shortfall 18/)).toBeInTheDocument();
    expect(screen.queryByText(/recorded/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('proc-event-row-0'));
    expect(screen.getByText(/Raw recorded payload/)).toBeInTheDocument();
  });

  it('shows quarantine and bitemporal transitions without action controls', () => {
    render(<ProcurementAuditPanel
      procCase={{ state_json: { split: { subtotal_cents: 120000 } } }}
      journey={[{ state: 'OPTIONS_READY', event: 'fulfillment_options_generated', actor_type: 'agent', valid_from: '2026-08-13T01:00:00Z', valid_to: null }]}
      quarantine={{ active: true, senderDomain: 'bad.example', reason: 'untrusted_sender', severity: 'high', route: 'security_review', securityReasons: ['domain_mismatch'], timestamp: '2026-08-13T01:00:00Z' }}
      canSeeOperatorDraft
      classNames={classes}
      humanize={value => String(value).replaceAll('_', ' ')}
    />);
    expect(screen.getByText(/No quote, price, inventory, economics, payment, or procurement state was applied/i)).toBeInTheDocument();
    expect(screen.getByTestId('proc-audit-trail')).toHaveTextContent(/current/);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
