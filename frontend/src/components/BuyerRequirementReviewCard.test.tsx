import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import BuyerRequirementReviewCard from './BuyerRequirementReviewCard';


describe('BuyerRequirementReviewCard', () => {
  it('requires an unchecked opt-in and sends the explicit cap only on acceptance', async () => {
    const accept = vi.fn().mockResolvedValue(undefined);
    render(<BuyerRequirementReviewCard claims={[{ claim_id: 'claim', attribute: 'ram_gb',
      operator: '>=', value: 32, requirement_class: 'minimum', constraint_tier: 'hard', authority_status: 'unverified' }]} onAccept={accept} />);
    const consent = screen.getByRole('checkbox', { name: 'Allow bounded stretch for this review only' });
    expect(consent).not.toBeChecked();
    fireEvent.click(consent);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Stretch maximum AUD per item' }), { target: { value: '3300' } });
    expect(accept).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Use selected provisionally' }));
    await waitFor(() => expect(accept).toHaveBeenCalledWith(['claim'], 'local_only', [], 330000));
  });
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
    expect(screen.getByRole('button', { name: 'Accept selected case evidence' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Research and corroborate' })).toBeNull();
  });
});
