import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import BuyerClaimReconciliationCard from '../BuyerClaimReconciliationCard';

describe('BuyerClaimReconciliationCard', () => {
  it('keeps all four evidence outcomes buyer-visible', () => {
    render(<BuyerClaimReconciliationCard rows={[
      { buyer_claim_id: 'a', attribute: 'ram_gb', status: 'corroborated', reason: 'Official floor matches.' },
      { buyer_claim_id: 'b', attribute: 'operating_system', status: 'contradicted', reason: 'Official value differs.' },
      { buyer_claim_id: 'c', attribute: 'storage_gb', status: 'unresolved', reason: 'No matching official claim.' },
      { buyer_claim_id: 'd', attribute: 'gpu_vram_gb', status: 'preference_only', reason: 'Buyer preference only.' },
    ]} />);

    const card = screen.getByTestId('buyer-claim-reconciliation');
    expect(card).toHaveTextContent(/ram gb: corroborated/i);
    expect(card).toHaveTextContent(/operating system: contradicted/i);
    expect(card).toHaveTextContent(/storage gb: unresolved/i);
    expect(card).toHaveTextContent(/gpu vram gb: preference only/i);
  });
});
