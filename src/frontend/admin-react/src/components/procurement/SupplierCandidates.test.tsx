import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SupplierCandidates from './SupplierCandidates';
import type { SupplierCandidate } from '../../api';

const base: SupplierCandidate = {
  supplier_id: 'sup-1',
  legal_name: 'Acme Distribution Pty Ltd',
  confidence: 0.82,
  contact_email: 'orders@acme.example',
  domain: 'acme.example',
  on_time_rate: 0.95,
  reliability: 0.9,
  lead_time_days: 5,
  prior_dealings: 3,
  last_invoice_cents: 123400,
  risk_tier: 'low',
  flags: [],
  recommended: true,
  provenance: { contact_email: 'kyv', domain: 'allowlist' },
} as SupplierCandidate;

describe('SupplierCandidates', () => {
  it('renders nothing when there are no candidates', () => {
    const { container } = render(<SupplierCandidates candidates={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders a card per candidate with name, confidence and contact', () => {
    render(<SupplierCandidates candidates={[base]} />);
    expect(screen.getByText('Acme Distribution Pty Ltd')).toBeInTheDocument();
    expect(screen.getAllByTestId('op-candidate')).toHaveLength(1);
    // confidence 0.82 -> 82%
    expect(screen.getByText(/confidence 82%/i)).toBeInTheDocument();
    expect(screen.getByTestId('op-candidate-contact')).toHaveTextContent('orders@acme.example');
    expect(screen.getByTestId('op-candidate-recommended')).toBeInTheDocument();
  });

  it('shows the "contact not verified" affordance and risk flags when present', () => {
    const risky: SupplierCandidate = {
      ...base,
      contact_email: null as unknown as string,
      recommended: false,
      flags: ['no_verified_contact', 'high_risk'],
    };
    render(<SupplierCandidates candidates={[risky]} />);
    expect(screen.getByText(/contact not verified/i)).toBeInTheDocument();
    expect(screen.queryByTestId('op-candidate-recommended')).toBeNull();
    const flags = screen.getAllByTestId('op-candidate-flag').map((n) => n.textContent);
    expect(flags.join(' ')).toMatch(/no verified contact/);
    expect(flags.join(' ')).toMatch(/high risk/);
  });
});
