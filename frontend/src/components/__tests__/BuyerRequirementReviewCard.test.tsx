import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
    expect(screen.getByLabelText(/Correct ram gb value/i)).toHaveValue('64');
  });

  it('renders nothing when there are no extracted claims', () => {
    const { container } = render(<BuyerRequirementReviewCard claims={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('submits an inline correction without granting authority', async () => {
    const onAccept = vi.fn().mockResolvedValue(undefined);
    render(<BuyerRequirementReviewCard claims={[{
      claim_id: 'claim-ram', attribute: 'ram_gb', operator: '>=', value: 64,
      unit: 'GB', requirement_class: 'recommended', constraint_tier: 'preferred',
      authority_status: 'unverified',
    }]} onAccept={onAccept} />);

    fireEvent.change(screen.getByLabelText(/Correct ram gb value/i), { target: { value: '48' } });
    fireEvent.click(screen.getByRole('button', { name: 'Use provisionally' }));
    await vi.waitFor(() => expect(onAccept).toHaveBeenCalledWith(
      ['claim-ram'], 'local_only', [expect.objectContaining({
        claim_id: 'claim-ram', value: 48, requirement_class: 'recommended',
      })],
    ));
  });
});
