import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SemanticResolutionTrace from '../SemanticResolutionTrace';

describe('SemanticResolutionTrace', () => {
  it('shows decomposition, coverage, authority and prevented state', () => {
    render(
      <SemanticResolutionTrace
        resolution={{
          outcome: 'clarify',
          catalog_authority: 'blocked',
          residual_route: 'ASK',
          residual_reasons: ['material_buyer_input_required'],
          concepts: [{ text: 'iron birch', status: 'unresolved' }],
          questions: [{ question: 'Which material identity is required?' }],
          state_prevented: ['catalog_recommendation', 'supplier_enquiry'],
          next_permitted_action: 'ask_material_clarification',
        }}
        evidence={{
          selected: ['concept_resolution'],
          legs: { concept_resolution: { data: { status: 'consent_required' } } },
        }}
      />,
    );

    expect(screen.getByTestId('semantic-resolution-trace')).toHaveTextContent('iron birch');
    expect(screen.getAllByText(/consent required/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/catalog recommendation/i)).toBeInTheDocument();
    expect(screen.getByText(/Which material identity/i)).toBeInTheDocument();
    expect(screen.getByTestId('semantic-residual-route')).toHaveTextContent('ASK');
    expect(screen.getByText(/material buyer input required/i)).toBeInTheDocument();
  });

  it('shows the exact governed search and candidate provenance without promoting it to fact', () => {
    render(
      <SemanticResolutionTrace
        resolution={{
          outcome: 'clarify',
          catalog_authority: 'blocked',
          desired_outcome: 'run engine digital-twin simulations',
          concepts: [{ text: 'digital twin', status: 'unresolved' }],
          questions: [{ question_id: 'software', question: 'Which software and version will run?' }],
          state_prevented: ['catalog_recommendation', 'inventory_fit_assumption'],
          next_permitted_action: 'ask_material_clarification',
        }}
        evidence={{
          selected: ['concept_resolution'],
          budget: { per_lane_ms: 2500, used_cost_units: 3, max_cost_units: 8 },
          ms: 41,
          legs: {
            concept_resolution: {
              health: 'healthy',
              data: {
                status: 'evidence_candidates',
                authority: 'evidence_candidate_only',
                query: 'digital twin definition requirements compatibility',
                query_hash: '0123456789abcdef',
                provider_id: 'approved_search_proxy',
                provider_run_status: 'cached',
                cache_status: 'hit',
                source_status: { status: 'full', hit_count: 1, latency_ms: 18 },
                items: [{
                  title: 'Digital twin requirements guide',
                  source_domain: 'docs.example.org',
                  url: 'https://docs.example.org/twins',
                  fetched_ts: 1785859200,
                }],
              },
            },
          },
        }}
      />,
    );

    const trace = screen.getByTestId('semantic-resolution-trace');
    expect(trace).toHaveTextContent('run engine digital-twin simulations');
    expect(trace).toHaveTextContent('digital twin definition requirements compatibility');
    expect(trace).toHaveTextContent('approved search proxy');
    expect(trace).toHaveTextContent('candidate only');
    expect(trace).toHaveTextContent('Digital twin requirements guide');
    expect(screen.getByRole('link', { name: /Digital twin requirements guide/ })).toHaveAttribute(
      'href', 'https://docs.example.org/twins',
    );
  });

  it('renders the qualified commercial authority chain without implying authorization', () => {
    render(
      <SemanticResolutionTrace
        resolution={{
          outcome: 'proceed_catalog',
          catalog_authority: 'permitted',
          residual_route: 'AUTHORIZE',
          residual_reasons: ['consequential_action_requires_policy'],
          concepts: [{ text: 'digital twin', status: 'resolved' }],
          questions: [],
          state_prevented: [],
          next_permitted_action: 'evaluate_consequential_action_policy',
          authorization_granted: false,
        }}
        evidence={{ selected: ['concept_resolution'], legs: { concept_resolution: { data: { status: 'complete' } } } }}
        alignment={{ status: 'qualified_catalog_match', qualified: ['RGAM-0007'] }}
        caseObligations={[{
          kind: 'buyer_commitment', status: 'authorization_required', residual_route: 'AUTHORIZE',
          selected_sku: 'RGAM-0007', quantity: 20,
          atp_snapshot: { source_version: 'ATP-42', observed_at: '2026-08-05T12:00:00Z' },
        }]}
      />,
    );

    const trace = screen.getByTestId('semantic-resolution-trace');
    expect(trace).toHaveTextContent(/qualified catalog match/i);
    expect(trace).toHaveTextContent('RGAM-0007');
    expect(trace).toHaveTextContent('ATP-42');
    expect(trace).toHaveTextContent(/authorization required/i);
    expect(trace).toHaveTextContent(/not granted/i);
  });

  it('labels a simulation qualification contract without implying live vendor proof', () => {
    render(
      <SemanticResolutionTrace
        resolution={{
          outcome: 'proceed_catalog',
          catalog_authority: 'permitted',
          residual_route: 'CONNECTOR',
          concepts: [{ text: 'digital twin simulation', status: 'resolved' }],
          questions: [],
          state_prevented: [],
          next_permitted_action: 'align_catalog',
        }}
        evidence={{
          selected: ['concept_resolution'],
          legs: { concept_resolution: { data: {
            status: 'simulation_fixture',
            authority: 'simulation_contract_only',
            query: 'digital twin simulation synthetic requirements',
            provider_id: 'deterministic_fixture:qualified_contract',
            provider_run_status: 'fixture_replay',
            cache_status: 'versioned_fixture',
            items: [],
          } } },
        }}
        alignment={{ status: 'qualified_catalog_match', qualified: ['RGAM-0007'] }}
      />,
    );

    expect(screen.getByTestId('semantic-resolution-trace')).toHaveTextContent(
      /synthetic qualification contract only/i,
    );
    expect(screen.getByTestId('semantic-resolution-trace')).toHaveTextContent(
      /not live vendor requirements or availability/i,
    );
  });
});
