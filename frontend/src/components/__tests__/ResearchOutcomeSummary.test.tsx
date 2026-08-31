import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ResearchOutcomeSummary from '../ResearchOutcomeSummary';

describe('ResearchOutcomeSummary', () => {
  it('shows parsed held claims instead of presenting them as no evidence', () => {
    render(<ResearchOutcomeSummary outcome={{
      schema_version: 'research-outcome-v1',
      case_id: 'sc-rockwell', case_revision: 4,
      discovery_status: 'completed', source_ownership_status: 'observed_held',
      fetch_status: 'completed', parsed_claim_count: 9, held_claim_count: 9,
      accepted_claim_count: 0, rejected_claim_count: 0,
      requirement_completeness: 'partial', catalog_authority: 'blocked',
      commerce_authority: 'none', next_action: 'independent_policy_review',
      failure_code: 'independent_policy_human_signoff_pending',
    }} />);

    const summary = screen.getByTestId('research-outcome-summary');
    expect(summary).toHaveTextContent(/Held for review/i);
    expect(summary).toHaveTextContent(/Parsed: 9.*Held: 9.*Accepted: 0/i);
    expect(summary).toHaveTextContent(/Catalog authority: blocked/i);
  });
});
