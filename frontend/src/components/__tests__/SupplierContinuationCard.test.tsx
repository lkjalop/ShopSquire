import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import SupplierContinuationCard, { commercialReviewReasons } from '../SupplierContinuationCard';

describe('SupplierContinuationCard', () => {
  it('shows concise fulfilment truth and keeps provenance in drill-down', () => {
    const confirm = vi.fn();
    const back = vi.fn();
    render(<SupplierContinuationCard journey={{
      caseId: 'sc-1', preferredSku: 'PREFERRED', preferredTitle: 'Preferred laptop',
      substituteSku: 'SUBSTITUTE', requestedQuantity: 30, availableNow: 12,
      unitPriceCents: 899_900, currency: 'AUD',
      selectionKey: 'select-1', confirmationKey: 'confirm-1',
      deadlineDays: 2, choices: [], selectedChoice: 'substitute', selectionId: 'fs-1',
      revision: 1, selectedOfferId: 'offer-exact', status: 'offers', offers: [
        { offer_id: 'offer-no', offered_sku: 'PREFERRED', relationship: 'exact', quantity_available: 0, response_status: 'rejected', response_reason: 'Supplier reported no available quantity.' },
        { offer_id: 'offer-exact', offered_sku: 'PREFERRED', relationship: 'exact', quantity_available: 18, lead_time_days: 8, response_status: 'accepted', response_reason: 'Exact balance supplied.' },
        { offer_id: 'offer-sub', offered_sku: 'SUBSTITUTE', relationship: 'compatible_substitute', quantity_available: 30, lead_time_days: 2, provenance: { supplier_reference: 'fixture-b' }, response_status: 'conditional', response_reason: 'Buyer acceptance required.' },
      ], proportionateAlternatives: [{
        sku: 'VALUE', title: 'Value laptop', priceCents: 699_900, currency: 'AUD',
        savingsCents: 200_000, savingsPercent: 22, fitStatus: 'conditional',
        compromise: 'Trade-off or unverified area: warranty.',
      }],
    }} onAssess={vi.fn()} onSelectChoice={vi.fn()} onSelectOffer={vi.fn()}
      onConfirm={confirm} onBack={back} onDismiss={vi.fn()} />);

    expect(screen.getByText(/12 verified now · 18 require/i)).toBeTruthy();
    const commercialReview = screen.getByTestId('high-value-order-warning');
    expect(commercialReview).toHaveTextContent(/total value is at least AUD 30,000/i);
    expect(commercialReview).toHaveTextContent(/quantity is over 10 and unit price is at least AUD 4,000/i);
    expect(commercialReview).toHaveTextContent(/portfolio enforcement: advisory only/i);
    expect(commercialReview).toHaveTextContent(/purchase authority: unchanged/i);
    expect(screen.getByTestId('proportionate-alternatives')).toHaveTextContent(/preferred technical fit remains selected/i);
    expect(screen.getByTestId('proportionate-alternatives')).toHaveTextContent(/22% lower/i);
    expect(screen.getByText(/unable to fulfil/i)).toBeTruthy();
    expect(screen.getByText(/REJECTED.*no available quantity/i)).toBeTruthy();
    expect(screen.getByText(/CONDITIONAL.*buyer acceptance required/i)).toBeTruthy();
    expect(screen.getByText(/12 × PREFERRED available now.*18 supplier-confirmed in 8 days/i)).toBeTruthy();
    expect(screen.getByText(/Supplier enquiry: not a purchase commitment/i)).toBeTruthy();
    expect(screen.getByTestId('real-supplier-locked')).toHaveTextContent(/human RFQ preview/i);
    fireEvent.click(screen.getByRole('button', { name: /confirm exact cart change/i }));
    expect(confirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: /change fulfilment choice/i }));
    expect(back).toHaveBeenCalledTimes(1);
  });

  it('does not trigger commercial review below the portfolio thresholds', () => {
    expect(commercialReviewReasons({
      requestedQuantity: 5, unitPriceCents: 399_900, currency: 'AUD',
    })).toEqual([]);
  });

  it('does not apply AUD thresholds to an unconverted native currency', () => {
    expect(commercialReviewReasons({
      requestedQuantity: 30, unitPriceCents: 899_900, currency: 'USD',
    })).toEqual([]);
  });
});
