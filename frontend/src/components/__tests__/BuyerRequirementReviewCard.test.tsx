import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import BuyerRequirementReviewCard from '../BuyerRequirementReviewCard';

describe('BuyerRequirementReviewCard', () => {
  it('renders verified official values as evidence, not editable uploaded claims', () => {
    render(<BuyerRequirementReviewCard claims={[
      { claim_id: 'steam-ram', attribute: 'ram_gb', operator: '>=', value: 8,
        unit: 'GB', requirement_class: 'minimum', constraint_tier: 'required', authority_status: 'verified_official' },
      { claim_id: 'steam-vram', attribute: 'gpu_vram_gb', operator: '>=', value: 2,
        unit: 'GB', requirement_class: 'minimum', constraint_tier: 'required', authority_status: 'verified_official' },
    ]} onAccept={vi.fn()} />);
    expect(screen.queryByText(/came from your upload/i)).toBeNull();
    expect(screen.queryByText(/no product has been qualified/i)).toBeNull();
    expect(screen.getByLabelText(/Correct ram gb value/i)).toHaveValue('8');
    expect(screen.getByLabelText(/Correct gpu vram gb value/i)).toHaveValue('2');
    expect(screen.getByLabelText(/Correct ram gb value/i)).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', {name:'Use selected provisionally'})).toBeNull();
  });
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

  it('does not crash when a degraded claim omits display labels', () => {
    render(<BuyerRequirementReviewCard claims={[{
      claim_id: 'partial', operator: '>=', value: 8,
      authority_status: 'unverified',
    } as any]} />);

    expect(screen.getAllByText(/not recorded/i).length).toBeGreaterThan(0);
  });

  it('submits an inline correction without granting authority', async () => {
    const onAccept = vi.fn().mockResolvedValue(undefined);
    render(<BuyerRequirementReviewCard claims={[{
      claim_id: 'claim-ram', attribute: 'ram_gb', operator: '>=', value: 64,
      unit: 'GB', requirement_class: 'recommended', constraint_tier: 'preferred',
      authority_status: 'unverified',
    }]} onAccept={onAccept} />);

    fireEvent.change(screen.getByLabelText(/Correct ram gb value/i), { target: { value: '48' } });
    fireEvent.click(screen.getByRole('button', { name: 'Use selected provisionally' }));
    await vi.waitFor(() => expect(onAccept).toHaveBeenCalledWith(
      ['claim-ram'], 'local_only', [expect.objectContaining({
        claim_id: 'claim-ram', value: 48, requirement_class: 'recommended',
      })],
    ));
  });

  it('surfaces canonical source claims pending independent policy review', () => {
    render(<BuyerRequirementReviewCard claims={[{
      claim_id: 'claim-emulate-ram', attribute: 'ram_gb', operator: '>=', value: 64,
      unit: 'GB', requirement_class: 'recommended', constraint_tier: 'preferred',
      authority_status: 'pending_independent_policy_review',
      source_policy_review: {
        status: 'automated_policy_checks_passed_human_signoff_pending',
        reviewer: 'source-policy-reviewer-v1',
        reviewed_at: '2026-08-25T00:00:00Z',
      },
    }]} onAccept={vi.fn()} />);

    expect(screen.getByText(/reviewed canonical publisher page/i)).toBeVisible();
    expect(screen.getByText(/independent source-policy review is signed off/i)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Use selected provisionally' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Reject all' })).toBeVisible();
    expect(screen.getByTestId('source-policy-review-receipt')).toHaveTextContent(
      /source-policy-reviewer-v1.*2026-08-25/i,
    );
    expect(screen.queryByRole('button', { name: 'Research and corroborate' })).toBeNull();
  });

  it('records an explicit reject-all action', async () => {
    const onAccept = vi.fn().mockResolvedValue(undefined);
    render(<BuyerRequirementReviewCard claims={[{
      claim_id: 'claim-reject', attribute: 'gpu', operator: 'contains', value: 'RTX',
      requirement_class: 'recommended', constraint_tier: 'preferred',
      authority_status: 'pending_independent_policy_review',
    }]} onAccept={onAccept} />);

    fireEvent.click(screen.getByRole('button', { name: 'Reject all' }));
    await vi.waitFor(() => expect(onAccept).toHaveBeenCalledWith([], 'local_only', []));
    expect(await screen.findByRole('status')).toHaveTextContent(/rejected all/i);
  });
});
