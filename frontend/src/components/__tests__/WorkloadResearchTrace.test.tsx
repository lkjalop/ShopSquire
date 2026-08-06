import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import WorkloadResearchTrace from '../WorkloadResearchTrace';

describe('WorkloadResearchTrace', () => {
  it('shows an unresolved provider search without fabricating evidence', () => {
    render(<WorkloadResearchTrace executionSteps={[
      {
        id: 'model-proposal', kind: 'model', authority: 'proposes',
        output: { workload_entities: [{ kind: 'software', name: 'Siemens NX 2025' }] },
      },
      {
        id: 'workload-evidence', kind: 'connector', authority: 'supplies_evidence',
        output: {
          live_allowed: false,
          consent_recorded: true,
          items: [{
            kind: 'software', requested_name: 'Siemens NX 2025', status: 'not_resolved',
            provider_coverage: 'none_for_kind', provider_attempts: [],
          }],
        },
      },
      {
        id: 'workload-authorization', kind: 'gate', authority: 'authorizes', status: 'blocked',
        output: { reason: 'named_workload_evidence_unresolved', state_prevented: ['catalog_qualification', 'supplier_rfq'] },
      },
    ]} />);

    expect(screen.getByTestId('research-model-entities')).toHaveTextContent('software: Siemens NX 2025');
    expect(screen.getByTestId('research-no-provider')).toHaveTextContent('No enrolled provider supports this workload kind');
    expect(screen.getByText(/Buyer consent recorded:/i)).toHaveTextContent('yes');
    expect(screen.getByText(/Live provider access for this workload:/i)).toHaveTextContent('no');
    expect(screen.getByText(/named workload evidence unresolved/i)).toBeInTheDocument();
    expect(screen.getByText(/catalog qualification \| supplier rfq/i)).toBeInTheDocument();
  });

  it('shows a provider-neutral plan and a blocked semantic evidence attempt', () => {
    render(<WorkloadResearchTrace executionSteps={[
      {
        id: 'model-proposal', kind: 'model', authority: 'proposes', output: {},
      },
      {
        id: 'research-plan', kind: 'stage', authority: 'plans', status: 'consent_required',
        output: {
          subject_spans: ['predictive maintenance simulation'],
          evidence_needs: [{
            need_id: 'requirements_1', subject_span: 'predictive maintenance simulation',
            claim_type: 'recommended_requirements', provider_capability: 'official_requirements',
          }],
          material_slots: [], max_provider_fanout: 3, total_timeout_ms: 2000,
          interpretation_origin: 'model',
          external_research_authorized: false,
        },
      },
      {
        id: 'semantic-evidence', kind: 'connector', authority: 'supplies_evidence',
        output: {
          legs: { concept_resolution: { found: false, data: { status: 'consent_required' } } },
        },
      },
      {
        id: 'semantic-authorization', kind: 'gate', authority: 'authorizes', status: 'blocked',
        output: {
          reasons: ['unresolved_material_concept'],
          state_prevented: ['catalog_recommendation', 'supplier_enquiry'],
        },
      },
    ]} />);

    expect(screen.getByTestId('research-model-entities')).toHaveTextContent('predictive maintenance simulation');
    expect(screen.getByTestId('research-evidence-needs')).toHaveTextContent('recommended requirements');
    expect(screen.getByText(/External research authorized:/i)).toHaveTextContent('no');
    expect(screen.getByText(/Interpretation source:/i)).toHaveTextContent('model');
    expect(screen.getByText(/Research status:/i)).toHaveTextContent('consent required');
    expect(screen.getByText(/Not attempted - buyer consent is required/i)).toBeInTheDocument();
    expect(screen.getByText(/^Status:/i)).toHaveTextContent('blocked');
  });
});
