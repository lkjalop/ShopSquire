import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ProcurementAuditPanel from '../ProcurementAuditPanel';
import ProcurementEventTable from '../ProcurementEventTable';
import PendingProcurementPlan from '../PendingProcurementPlan';
import SupplierRfqTracePanel from '../SupplierRfqTracePanel';

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

  it('keeps supplier identity and message content operator-only', () => {
    const activeCase = { state: 'RFQ_DRAFTED', state_json: { availability: { requested_qty: 30, in_stock: 12, shortfall: 18 } } };
    const draft = {
      recipient_ref: 'supplier-a', recipient_domain: 'supplier.example', subject: 'Quote 18 units',
      body: 'Please quote 18 exact units.', commercial_scope: { quantity: 18 },
      channel_plan: { channel: 'email', agent_may_draft: true },
      send_gate: { decision: 'human_review_required', reasons: [] },
    };
    const { rerender } = render(<SupplierRfqTracePanel
      cases={[activeCase]} activeCase={activeCase} draft={draft}
      procurementTrace={{ quantity: 18, channel: 'email' }} history={{ case_count: 1 }}
      integrityEvents={[]} canSeeOperatorDraft classNames={classes}
    />);
    expect(screen.getByTestId('proc-rfq-recipient')).toHaveTextContent('supplier.example');
    expect(screen.getByTestId('proc-rfq-body')).toHaveTextContent('Please quote 18 exact units');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();

    rerender(<SupplierRfqTracePanel
      cases={[activeCase]} activeCase={activeCase} draft={draft}
      procurementTrace={{ quantity: 18, channel: 'email' }} history={{ case_count: 1 }}
      integrityEvents={[]} canSeeOperatorDraft={false} classNames={classes}
    />);
    expect(screen.getByTestId('proc-rfq-safe-summary')).toHaveTextContent('18 supplier-shortfall');
    expect(screen.queryByText('supplier.example')).not.toBeInTheDocument();
    expect(screen.queryByText(/Please quote 18 exact units/)).not.toBeInTheDocument();
  });

  it('shows quarantined drafts and pending sourcing without granting an action', () => {
    const { rerender } = render(<SupplierRfqTracePanel
      cases={[]} activeCase={null} draft={null} procurementTrace={null} history={null}
      integrityEvents={[{ id: 'guard-1', payload: { action: 'block', recipient_domain: 'bad.example', findings: ['prompt_injection'] } }]}
      canSeeOperatorDraft classNames={classes}
    />);
    expect(screen.getByTestId('proc-integrity-guard')).toHaveTextContent(/BLOCKED.*bad.example.*prompt_injection/);

    rerender(<PendingProcurementPlan plan={{
      split: { now: [{ sku: 'LAP-A', qty: 12 }], later: [{ sku: 'LAP-A', qty: 18, supplier_ref: 'supplier-a', eta_days: 8 }] },
      suppliers: { 'supplier-a': { name: 'Synthetic Supplier A', channel: 'email' } },
    }} />);
    expect(screen.getByTestId('proc-pending-plan')).toHaveTextContent('12 ship from stock · 18 require supplier reorder');
    expect(screen.getByText(/18 × LAP-A/)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
