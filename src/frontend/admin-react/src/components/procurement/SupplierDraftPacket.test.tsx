import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SupplierDraftPacket from './SupplierDraftPacket';

describe('supplier outreach packet', () => {
  it('shows a portal preference as a human task, not an email delivery', () => {
    render(<SupplierDraftPacket
      draft={{
        subject: 'RFQ', body: 'Draft', content_hash: 'abcdef1234',
        recipient_domain: 'supplier.example', commercial_scope: { item_ref: 'SKU-1', quantity: 20 },
        channel_plan: { channel: 'portal', requires_human: true, rationale: 'Supplier accepts portal submissions.' },
        supplier_terms: { moq: 10, lead_time_days: 5, contract_status: 'preferred' },
      }}
      state="AWAITING_APPROVAL" recipientDisplay="supplier.example" draftEvidence={[]}
      draftChanged={false} editSubject="RFQ" setEditSubject={() => {}}
      editBody="Draft" setEditBody={() => {}} busy={false} onSaveEdit={() => {}}
    />);

    expect(screen.getByTestId('op-supplier-channel')).toHaveTextContent('PORTAL');
    expect(screen.getByTestId('op-supplier-channel')).toHaveTextContent('Human operator');
    expect(screen.getByTestId('op-supplier-channel')).toHaveTextContent('will not send');
    expect(screen.getByTestId('op-supplier-terms')).toHaveTextContent('MOQ 10');
  });
});
