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
});

