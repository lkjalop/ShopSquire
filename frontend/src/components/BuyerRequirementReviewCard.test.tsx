import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import BuyerRequirementReviewCard from './BuyerRequirementReviewCard';


describe('BuyerRequirementReviewCard', () => {
  it('renders critic-accepted case origin claims with their real authority and action', () => {
    render(<BuyerRequirementReviewCard claims={[{
      claim_id: 'claim-1',
      attribute: 'ram_gb',
      operator: '>=',
      value: 32,
      unit: 'GB',
      requirement_class: 'minimum',
      constraint_tier: 'hard',
      authority_status: 'case_origin_critic_accepted',
    }]} onAccept={async () => {}} />);

    expect(screen.getByText(/exact publisher origin/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept case evidence' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Research and corroborate' })).toBeNull();
  });
});
