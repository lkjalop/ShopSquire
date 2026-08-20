import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import WorkloadResearchTrace from '../WorkloadResearchTrace';

describe('WorkloadResearchTrace', () => {
  it('does not claim that missing research records prove research was unnecessary', () => {
    render(<WorkloadResearchTrace executionSteps={[]} />);

    expect(screen.getByText(/No governed workload research record was produced/i)).toBeInTheDocument();
    expect(screen.queryByText(/research was not required/i)).not.toBeInTheDocument();
  });

  it('renders a provisional ambiguity plan without claiming external execution', () => {
    render(<WorkloadResearchTrace executionSteps={[]} events={[{
      event_type: 'ambiguity_exploration_projected',
      payload: {
        retained_purpose: 'I need digital twin simulation and to simulate a cyber attack.',
        research_plan_id: 'plan-ot-range',
        interpretations: [
          { hypothesis_id: 'digital-twin', label: 'Digital twin simulation' },
          { hypothesis_id: 'ot-cyber', label: 'Simulate a cyber attack' },
        ],
        research_obligations: [
          { obligation_id: 'official', kind: 'official requirements', resolution_owner: 'research' },
        ],
        execution: 'local_exploration_completed',
        evidence: 'material_gaps',
        decision: 'exploration_allowed',
        cart_authority: 'none',
        provider_accounting: { external_calls: 0, paid_calls: 0 },
        canonical_truth: {
          research_execution: 'NOT_ATTEMPTED', evidence_status: 'NONE',
          freshness: 'UNKNOWN', decision_status: 'PROVISIONAL', commerce_authority: 'NONE',
        },
      },
    }]} />);

    const trace = screen.getByTestId('workload-research-trace');
    expect(trace).toHaveTextContent(/bounded research plan/i);
    expect(trace).toHaveTextContent(/digital twin simulation/i);
    expect(trace).toHaveTextContent(/simulate a cyber attack/i);
    expect(trace).toHaveTextContent(/Status: not executed/i);
    expect(trace).toHaveTextContent(/External calls: 0/i);
    expect(screen.getByTestId('canonical-procurement-truth')).toHaveTextContent(
      /research: not attempted.*evidence: none.*freshness: unknown/i,
    );
    expect(trace).toHaveTextContent(/not an external fetch or verified product fit/i);
    expect(screen.queryByText(/No governed workload research record was produced/i)).toBeNull();
  });

  it('renders every governed ladder rung and engine-level degradation truth', () => {
    render(<WorkloadResearchTrace executionSteps={[]} events={[{
      event_type: 'official_research_rerank_completed',
      payload: {
        evidence_ladder: [
          { tier: 0, mechanism: 'evidence_cache', execution_status: 'miss', rejection_reason: 'cache_miss', billing_class: 'free' },
          { tier: 4, mechanism: 'self_hosted_discovery', execution_status: 'degraded', rejection_reason: 'engines_captcha', billing_class: 'free', dispatch_count: 1, allowlisted_result_count: 0, engines_queried: ['mojeek', 'bing'], engines_responded: ['bing'], engine_failures: [{ engine: 'startpage', reason: 'CAPTCHA' }] },
          { tier: 5, mechanism: 'paid_discovery', execution_status: 'not_attempted', rejection_reason: 'provider_not_enrolled', billing_class: 'paid' },
          { tier: 6, mechanism: 'governed_abstention', execution_status: 'activated', rejection_reason: 'material_evidence_unresolved', billing_class: 'not_applicable' },
        ],
      },
    }]} />);

    const ladder = screen.getByTestId('governed-evidence-ladder');
    expect(ladder).toHaveTextContent(/Tier 0: evidence cache.*miss.*cache miss/i);
    expect(ladder).toHaveTextContent(/Tier 4: self hosted discovery.*degraded.*engines captcha/i);
    expect(ladder).toHaveTextContent(/Queried: mojeek, bing.*Responded: bing/i);
    expect(ladder).toHaveTextContent(/startpage: CAPTCHA/i);
    expect(ladder).toHaveTextContent(/Tier 5: paid discovery.*not attempted/i);
    expect(ladder).toHaveTextContent(/Tier 6: governed abstention.*activated/i);
    expect(ladder).toHaveTextContent(/infrastructure failure is not an evidence conclusion/i);
  });

  it('finds governed research after trace taxonomy normalizes the event type', () => {
    render(<WorkloadResearchTrace executionSteps={[]} events={[{
      event_type: 'feedback_loop',
      payload: {
        _original_event_type: 'official_research_rerank_completed',
        evidence_ladder: [
          { tier: 0, mechanism: 'evidence_cache', execution_status: 'completed', billing_class: 'free' },
          { tier: 1, mechanism: 'enrolled_canonical_origin', execution_status: 'completed', billing_class: 'free' },
        ],
      },
    }]} />);

    expect(screen.getByTestId('governed-evidence-ladder')).toHaveTextContent(/Tier 0: evidence cache/i);
    expect(screen.getByTestId('governed-evidence-ladder')).toHaveTextContent(/Tier 1: enrolled canonical origin/i);
    expect(screen.queryByText(/No governed workload research record was produced/i)).toBeNull();
  });

  it('retains research authorization and later obligations on the shopping-case trace', () => {
    render(<WorkloadResearchTrace executionSteps={[]} events={[
      {
        event_type: 'ambiguity_exploration_projected',
        payload: { research_plan_id: 'crp-case', retained_purpose: 'factory simulation' },
      },
      {
        event_type: 'official_research_rerank_completed',
        payload: {
          evidence_ladder: [{ tier: 1, mechanism: 'enrolled_canonical_origin', execution_status: 'completed', billing_class: 'free' }],
        },
      },
      {
        event_type: 'shopping_case_obligations_retained',
        payload: { obligations: [{ kind: 'quantity', resolution_owner: 'buyer', buyer_text: 'reduce it by 10 units' }] },
      },
    ]} />);

    expect(screen.getByText(/Buyer consent recorded:/i)).toHaveTextContent('yes');
    expect(screen.getByTestId('shopping-case-retained-obligations')).toHaveTextContent(/quantity.*owner: buyer/i);
    expect(screen.getByTestId('shopping-case-retained-obligations')).toHaveTextContent(/reduce it by 10 units/i);
  });

  it('finds canonical research initiated from a buyer-provided official source', () => {
    render(<WorkloadResearchTrace executionSteps={[]} events={[{
      event_type: 'feedback_loop',
      payload: {
        _original_event_type: 'buyer_evidence_source_researched',
        evidence_ladder: [
          { tier: 1, mechanism: 'enrolled_canonical_origin', execution_status: 'completed', billing_class: 'free' },
        ],
      },
    }]} />);

    expect(screen.getByTestId('governed-evidence-ladder')).toHaveTextContent(/enrolled canonical origin/i);
    expect(screen.queryByText(/No governed workload research record was produced/i)).toBeNull();
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
        id: 'research-trigger-observer', kind: 'observer', authority: 'observes',
        status: 'research_candidate', output: {
          state: 'unresolved_workload', recommendation: 'research_candidate', score: 0.72,
          reasons: ['material_semantic_concept', 'material_unknowns'], authoritative: false,
        },
      },
      {
        id: 'research-trigger-post-catalog-observer', kind: 'observer', authority: 'observes',
        output: { features: {
          qualified_product_count: 0, catalog_coverage_gap: 1, unknown_attribute_ratio: 0,
        } },
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
          query_bundle: [{
            query_id: 'requirements_1', strategy: 'requirements',
            text: 'predictive maintenance simulation official recommended system requirements',
            prohibited_assumptions: ['unverified_vendor'],
          }],
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
    expect(screen.getByTestId('research-trigger-observer')).toHaveTextContent(/cannot authorize research/i);
    expect(screen.getByTestId('research-trigger-post-catalog-observer')).toHaveTextContent(/Qualified products:\s*0/i);
    expect(screen.getByTestId('research-query-bundle')).toHaveTextContent(/planned only; no authority/i);
    expect(screen.getByTestId('research-query-bundle')).toHaveTextContent(/unverified vendor/i);
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

  it('renders provider timeout as degraded research rather than empty success', () => {
    render(<WorkloadResearchTrace executionSteps={[{
      id: 'semantic-evidence', kind: 'connector', authority: 'supplies_evidence',
      output: { legs: { concept_resolution: {
        found: false, health: 'timed_out', error: 'leg_timeout>1800ms', data: {},
      } } },
    }]} />);

    expect(screen.getByText(/provider timeout/i)).toBeInTheDocument();
    expect(screen.getByText(/Provider status:/i)).toHaveTextContent(/leg timeout>1800ms/i);
    expect(screen.queryByText(/attempted empty/i)).not.toBeInTheDocument();
  });

  it('renders admission rejection as internal effort state and never provider spend', () => {
    render(<WorkloadResearchTrace executionSteps={[{
      id: 'semantic-evidence', kind: 'connector', authority: 'supplies_evidence',
      output: {
        effort: { used_effort_units: 3, max_effort_units: 3 },
        provider_usage: {
          external_provider_call_count: 0,
          paid_provider_call_count: null,
          paid_provider_call_count_status: 'not_recorded',
        },
        legs: { web: {
          found: false,
          health: 'rejected',
          execution_status: 'rejected_admission',
          error: 'effort_allowance_exceeded',
          data: {},
        } },
      },
    }]} />);

    expect(screen.getByText(/not started\s+internal effort admission rejected/i)).toBeInTheDocument();
    expect(screen.getByText(/Internal scheduler status/i)).toHaveTextContent(/effort allowance exceeded/i);
    expect(screen.queryByText(/Provider status:/i)).not.toBeInTheDocument();
    expect(screen.getByTestId('research-provider-usage')).toHaveTextContent(/External provider calls:\s*0/i);
    expect(screen.getByTestId('research-provider-usage')).toHaveTextContent(/Paid calls:\s*not recorded/i);
  });

  it('distinguishes live research, cache reuse, and discovery engine health', () => {
    render(<WorkloadResearchTrace executionSteps={[]} events={[{
      event_type: 'official_research_rerank_completed',
      payload: {
        status: 'completed', evidence_outcome: 'product_requirements',
        provider_accounting: {
          external_calls: 2, official_origin_fetches: 1, cache_hits: 0, paid_calls: 0,
        },
        evidence_ladder: [{
          tier: 4, mechanism: 'self_hosted_discovery', execution_status: 'completed',
          billing_class: 'free', dispatch_count: 1, allowlisted_result_count: 3,
          engines_queried: ['bing', 'google'], engines_responded: ['bing'],
          engine_reliability: [
            { engine: 'bing', health: 'healthy', latency_ms: 421 },
            { engine: 'google', health: 'degraded', latency_ms: 1800 },
          ],
          suppressed_engines: ['wikipedia'],
        }],
      },
    }]} />);

    expect(screen.getByTestId('official-research-outcome')).toHaveTextContent(/Execution source:\s*live network/i);
    expect(screen.getByTestId('discovery-engine-health')).toHaveTextContent(/bing: healthy \(421ms\)/i);
    expect(screen.getByTestId('discovery-engine-health')).toHaveTextContent(/google: degraded \(1800ms\)/i);
    expect(screen.getByText(/Temporarily suppressed:/i)).toHaveTextContent(/wikipedia/i);
  });

  it('shows query-proposal fallback without granting research or commerce authority', () => {
    render(<WorkloadResearchTrace executionSteps={[]} events={[{
      event_type: 'open_world_discovery_completed',
      payload: {
        provider_accounting: { external_calls: 3, paid_calls: 0 },
        query_proposal: {
          status: 'rejected_or_unavailable', model_calls: 1, latency_ms: 6000,
          reason: 'ReadTimeout', authority: 'none',
        },
      },
    }]} />);

    expect(screen.getByTestId('open-world-query-proposal')).toHaveTextContent(/rejected or unavailable/i);
    expect(screen.getByTestId('open-world-query-proposal')).toHaveTextContent(/ReadTimeout/i);
    expect(screen.getByTestId('open-world-query-proposal')).toHaveTextContent(/Authority:\s*none/i);
  });

  it('separates origin consistency from independently verified publisher ownership', () => {
    render(<WorkloadResearchTrace executionSteps={[]} events={[{
      event_type: 'case_publisher_origin_researched',
      payload: {
        provider_accounting: { external_calls: 1, paid_calls: 0 },
        publisher_origin_verification: {
          status: 'origin_consistent',
          ownership_authority: 'not_independently_verified',
          reasons: ['identity_matches_origin_host', 'document_matches_buyer_subject'],
        },
      },
    }]} />);

    const panel = screen.getByTestId('publisher-origin-verification');
    expect(panel).toHaveTextContent(/origin consistent/i);
    expect(panel).toHaveTextContent(/not independently verified/i);
    expect(panel).toHaveTextContent(/not proof of corporate ownership/i);
  });
});
