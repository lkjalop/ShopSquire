import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ProductWhyEvidence, { hasRetainedRankingEvidence } from '../ProductWhyEvidence';

describe('ProductWhyEvidence', () => {
  it('refuses a verified-best-fit claim when ranking evidence was not retained', () => {
    const explanation = {
      reason_summary: 'This product is verified in the catalogue.',
      matched_constraints: [],
      rank_factors: [],
      alternatives_not_selected: [],
    };

    expect(hasRetainedRankingEvidence(explanation)).toBe(false);
    render(<ProductWhyEvidence explanation={explanation} />);

    expect(screen.getByRole('status')).toHaveTextContent('Ranking evidence unavailable');
    expect(screen.getByRole('status')).toHaveTextContent('should not be treated as a verified best fit');
    expect(screen.queryByText(explanation.reason_summary)).not.toBeInTheDocument();
  });

  it('renders the returned explanation when ranking evidence exists', () => {
    render(
      <ProductWhyEvidence
        explanation={{
          matched_constraints: ['budget <= AUD 2,000'],
          rank_factors: [{ code: 'budget_fit' }],
          disqualifiers: [],
          alternatives_not_selected: [{ sku: 'ALT-1' }],
          reason_summary: 'Within the stated budget.',
        }}
      />,
    );

    expect(screen.getByText(/budget <= AUD 2,000/)).toBeInTheDocument();
    expect(screen.getByText(/Within the stated budget/)).toBeInTheDocument();
    expect(screen.queryByText(/Ranking evidence unavailable/)).not.toBeInTheDocument();
  });

  it('renders canonical workload fit before ranking evidence', () => {
    render(
      <ProductWhyEvidence
        explanation={{
          sku: 'LAP-2',
          workload_summary: 'simulate mechanical-machine maintenance',
          qualification_scope: 'bounded_requirements',
          coverage_status: 'partial',
          fit_ledger: [{
            attribute: 'ram_gb',
            required: [['>=', 32]],
            observed: 64,
            verdict: 'meets',
            requirement_source: 'authoritative_external_evidence',
            requirement_evidence_refs: ['official:ram'],
          }],
          matched_constraints: [],
          rank_factors: [],
          alternatives_not_selected: [],
        }}
      />,
    );

    expect(screen.getByText(/simulate mechanical-machine maintenance/i)).toBeInTheDocument();
    expect(screen.getByText(/ram gb/i)).toBeInTheDocument();
    expect(screen.getByText(/64/)).toBeInTheDocument();
    expect(screen.getAllByText(/partial/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Ranking evidence unavailable/)).not.toBeInTheDocument();
  });
});
