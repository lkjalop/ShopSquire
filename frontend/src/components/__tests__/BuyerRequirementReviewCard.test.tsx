import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import BuyerRequirementReviewCard from '../BuyerRequirementReviewCard';

describe('BuyerRequirementReviewCard', () => {
  it('labels uploaded claims as provisional and non-authoritative', () => {
    render(<BuyerRequirementReviewCard claims={[{
      claim_id: 'claim-ram',
      attribute: 'ram_gb',
      operator: '>=',
      value: 64,
      unit: 'GB',
      requirement_class: 'recommended',
      constraint_tier: 'preferred',
      authority_status: 'unverified',
    }]} />);

    expect(screen.getByRole('region', { name: /review extracted requirements/i })).toBeVisible();
    expect(screen.getByText(/provisional and unverified/i)).toBeVisible();
    expect(screen.getByText(/no cart action was authorized/i)).toBeVisible();
    expect(screen.getByText(/ram gb/i)).toBeVisible();
    expect(screen.getByText(/>= 64 GB/i)).toBeVisible();
  });

  it('renders nothing when there are no extracted claims', () => {
    const { container } = render(<BuyerRequirementReviewCard claims={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
