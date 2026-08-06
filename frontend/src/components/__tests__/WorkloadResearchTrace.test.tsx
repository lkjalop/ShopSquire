import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import WorkloadResearchTrace from '../WorkloadResearchTrace';

describe('WorkloadResearchTrace', () => {
  it('does not claim that missing research records prove research was unnecessary', () => {
    render(<WorkloadResearchTrace executionSteps={[]} />);

    expect(screen.getByText(/No governed workload research record was produced/i)).toBeInTheDocument();
    expect(screen.queryByText(/research was not required/i)).not.toBeInTheDocument();
  });

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

  it('makes pending quantity arithmetic and its authorization boundary explicit', () => {
    render(<WorkloadResearchTrace executionSteps={[
      {
        id: 'commercial-case-reducer', kind: 'stage', authority: 'proposes', status: 'pending_confirmation',
        output: {
          prior_quantity: 30,
          obligations: [{
            kind: 'quantity_amendment', field_name: 'quantity', proposed_value: 20,
            status: 'pending_confirmation', authorization_granted: false,
          }],
        },
      },
      {
        id: 'semantic-authorization', kind: 'gate', authority: 'authorizes', status: 'blocked',
        output: { reasons: ['unresolved_material_concept'], state_prevented: ['catalog_recommendation'] },
      },
    ]} />);

    const commercial = screen.getByTestId('commercial-case-trace');
    expect(commercial).toHaveTextContent(/Prior quantity:\s*30/i);
    expect(commercial).toHaveTextContent(/Proposed value:\s*20/i);
    expect(commercial).toHaveTextContent(/requires buyer confirmation/i);
  });

  it('shows a buyer clarification as a non-authoritative research candidate', () => {
    render(<WorkloadResearchTrace executionSteps={[
      {
        id: 'research-plan', kind: 'stage', authority: 'plans', status: 'authorized',
        output: {
          external_research_authorized: true,
          material_slots: [{
            slot_id: 'software_or_standard',
            question: 'Which workflow and execution target must be supported?',
            answer_status: 'candidate',
            answer_candidate: 'Local engineering simulation with 3D visualisation.',
          }],
          evidence_needs: [{
            need_id: 'requirements_1', claim_type: 'recommended_requirements',
            subject_span: 'maintenance digital twin', provider_capability: 'official_requirements',
          }],
        },
      },
      {
        id: 'semantic-authorization', kind: 'gate', authority: 'authorizes', status: 'blocked',
        output: { reasons: ['authoritative_requirements_unavailable'], state_prevented: ['catalog_recommendation'] },
      },
    ]} />);

    expect(screen.getByText(/Local engineering simulation with 3D visualisation/i))
      .toHaveTextContent(/buyer-authored; awaiting authoritative evidence/i);
    expect(screen.getAllByText(/Status:/i).some((node) => /blocked/i.test(node.textContent || ''))).toBe(true);
  });
});
