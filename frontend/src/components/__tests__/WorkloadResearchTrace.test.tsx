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

  it('shows model hypotheses, provider attempts, and expected-impact clarification honestly', () => {
    render(<WorkloadResearchTrace executionSteps={[
      {
        id: 'semantic-evidence', kind: 'connector', authority: 'supplies_evidence',
        output: {
          legs: {
            concept_resolution: {
              found: false,
              data: {
                status: 'not_configured',
                provider_attempts: [{
                  provider_id: null, status: 'not_configured', capability: 'official_requirements',
                }],
              },
            },
          },
        },
      },
      {
        id: 'semantic-authorization', kind: 'gate', authority: 'authorizes', status: 'blocked',
        output: {
          workload_hypotheses: [
            {
              hypothesis_id: 'local', label: 'Local execution', confidence: 0.61,
              evidence_coverage: 'partial', matched_claim_types: ['compatibility'],
            },
            { hypothesis_id: 'remote', label: 'Remote client', confidence: 0.32 },
          ],
          material_unknowns: [{
            unknown_id: 'execution-location', description: 'Execution location',
            resolution_source: 'buyer',
          }],
          reasons: ['unresolved_material_concept'],
          state_prevented: ['catalog_recommendation'],
        },
      },
      {
        id: 'material-clarification', kind: 'gate', authority: 'requests_buyer_input',
        status: 'awaiting_buyer',
        output: {
          question: 'Will it run locally, remotely, or in a hybrid setup?',
          missing_slots: ['execution-location'],
          decision_impacts: ['architecture', 'product_set'],
          selection_policy: 'bounded_information_gain',
          hypotheses_discriminated: 2,
        },
      },
    ]} />);

    expect(screen.getByTestId('research-hypotheses')).toHaveTextContent(/proposed, not accepted/i);
    expect(screen.getByTestId('research-hypotheses')).toHaveTextContent(/evidence coverage: partial/i);
    expect(screen.getByTestId('research-hypotheses')).toHaveTextContent(/compatibility/i);
    expect(screen.getByTestId('research-material-unknowns')).toHaveTextContent(/resolved by buyer/i);
    expect(screen.getByTestId('semantic-provider-attempts')).toHaveTextContent(/No configured provider: not configured/i);
    const clarification = screen.getByTestId('material-clarification-trace');
    expect(clarification).toHaveTextContent(/execution location/i);
    expect(clarification).toHaveTextContent(/architecture \| product set/i);
    expect(clarification).toHaveTextContent(/Hypotheses distinguished:\s*2/i);
    expect(clarification).toHaveTextContent(/does not itself authorize/i);
  });

  it('shows accepted provider claims after deterministic requirement compilation', () => {
    render(<WorkloadResearchTrace executionSteps={[
      {
        id: 'semantic-evidence', kind: 'connector', authority: 'supplies_evidence',
        output: { legs: { concept_resolution: { found: true, data: { status: 'resolved' } } } },
      },
      {
        id: 'semantic-requirements-compiler', kind: 'gate', authority: 'compiles_constraints',
        status: 'accepted',
        output: {
          compiled_requirements: [
            { attribute_key: 'ram_gb', operator: '>=', value: 32, unit: 'GB' },
            { attribute_key: 'gpu_vram_gb', operator: '>=', value: 8, unit: 'GB' },
          ],
          rejected_claims: [],
        },
      },
      {
        id: 'semantic-authorization', kind: 'gate', authority: 'authorizes', status: 'accepted',
        output: { reasons: [], state_prevented: [] },
      },
    ]} />);

    expect(screen.getByTestId('compiled-requirements')).toHaveTextContent('ram gb >= 32 GB');
    expect(screen.getByTestId('compiled-requirements')).toHaveTextContent('gpu vram gb >= 8 GB');
    expect(screen.getByText(/Accepted official evidence may establish fit predicates/i))
      .toBeInTheDocument();
  });
});
