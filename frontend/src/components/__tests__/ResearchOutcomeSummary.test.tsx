import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ResearchOutcomeSummary from '../ResearchOutcomeSummary';

describe('ResearchOutcomeSummary', () => {
  it('renders missing obligations and pinned scope from the terminal contract', () => {
    render(<ResearchOutcomeSummary outcome={{
      schema_version: 'research-outcome-v1', case_id: 'case', case_revision: 2,
      discovery_status: 'completed', source_ownership_status: 'verified', fetch_status: 'completed',
      parsed_claim_count: 2, held_claim_count: 0, accepted_claim_count: 2, rejected_claim_count: 0,
      requirement_completeness: 'partial', catalog_authority: 'blocked', commerce_authority: 'none',
      missing_requirement_attributes: ['cpu_model', 'os'],
      literal_requirement_observations: [{observation_id: 'obs-1', canonical_title: 'Unseen subject',
        attribute_key: 'gpu_model', value: 'GPU A OR GPU B', disposition: 'observed', fit_authority: 'none'}],
      compilation_scopes: [{tenant_id: 'tenant-a', product_type: 'el-6-6',
        relationship: 'RUN_SUBJECT_ON_PRODUCT', manifest_id: 'electronics', manifest_revision: 'a'.repeat(64)}],
    }} />);
    expect(screen.getByTestId('research-outcome-summary')).toHaveTextContent('Missing requirements: cpu model, os');
    expect(screen.getByTestId('research-outcome-summary')).toHaveTextContent('electronics');
    expect(screen.getByTestId('research-outcome-summary')).toHaveTextContent('el-6-6');
    expect(screen.getByTestId('research-outcome-summary')).toHaveTextContent('GPU A OR GPU B');
    expect(screen.getByTestId('research-outcome-summary')).toHaveTextContent('not compatibility verification');
    expect(screen.getByTestId('research-outcome-summary')).not.toHaveTextContent('Verified evidence');
    expect(screen.getByTestId('research-outcome-summary')).toHaveTextContent('Publisher ownership verified');
  });
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
