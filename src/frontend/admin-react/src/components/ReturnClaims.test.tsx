import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReturnClaims } from './ReturnClaims';

vi.mock('../api', () => ({
  fetchReturnClaims: vi.fn(),
  fetchReturnClaim: vi.fn(),
  transitionReturnClaim: vi.fn(),
  setReturnEvidenceLegalHold: vi.fn(),
  downloadAuthenticated: vi.fn(),
}));

import * as api from '../api';

const claim = {
  claim_id: 'claim-1', sku: 'SKU-1', status: 'evidence_pending',
  order_verification_status: 'found', abuse_status: 'review_required',
  abuse_reasons: ['duplicate_evidence_review'],
  evidence_job: { status: 'quarantined', security_status: 'quarantined', visual_status: 'completed' },
  evidence: [{
    evidence_id: 'evidence-1', filename: 'receipt.pdf', cipher: 'AES-256-GCM',
    encryption_key_id: 'v1', retention_until: '2027-08-04T00:00:00Z', legal_hold: false,
  }],
  timeline: [{ sequence: 1, event_type: 'claim_received', to_status: 'evidence_pending' }],
};

describe('return claims operator console', () => {
  beforeEach(() => {
    vi.mocked(api.fetchReturnClaims).mockResolvedValue({ claims: [claim] });
    vi.mocked(api.fetchReturnClaim).mockResolvedValue(claim);
    vi.mocked(api.setReturnEvidenceLegalHold).mockResolvedValue({ legal_hold: true });
  });

  it('distinguishes review signals from fraud and exposes owner custody controls', async () => {
    render(<ReturnClaims role="owner" />);
    fireEvent.click(await screen.findByRole('button', { name: /SKU-1/i }));
    expect(await screen.findByText(/This is not a fraud finding/i)).toBeInTheDocument();
    expect(screen.getByText(/Security: quarantined/i)).toBeInTheDocument();
    expect(screen.getByText(/AES-256-GCM/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Place hold' }));
    await waitFor(() => expect(api.setReturnEvidenceLegalHold).toHaveBeenCalledWith(
      'claim-1', 'evidence-1', true, expect.any(String),
    ));
  });

  it('does not expose break-glass evidence controls to merchant role', async () => {
    render(<ReturnClaims role="merchant" />);
    fireEvent.click(await screen.findByRole('button', { name: /SKU-1/i }));
    await screen.findByText(/Encrypted evidence custody/i);
    expect(screen.queryByRole('button', { name: 'Audited access' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Place hold' })).not.toBeInTheDocument();
  });
});
