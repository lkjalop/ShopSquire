import { describe, expect, it } from 'vitest';

import {
  compactStateTimeline,
  compactAuthorityPath,
  deriveTraceTrustStrip,
  legacyComponentOntology,
  normalizeTraceLeaf,
  procurementQuarantineView,
  resolveWhyAnchorSections,
  TRACE_SECTIONS,
  traceSectionForLeaf,
} from '../DecisionTrace';

describe('Decision Trace component ontology', () => {
  it('keeps all 15 leaves reachable through six sections', () => {
    const leaves = TRACE_SECTIONS.flatMap((section) => [...section.leaves]);
    expect(TRACE_SECTIONS).toHaveLength(6);
    expect(new Set(leaves).size).toBe(15);
    expect(leaves).toEqual(expect.arrayContaining([
      'summary', 'events', 'execution', 'research', 'why', 'intent', 'memory', 'complexity',
      'evidence', 'multimodal', 'security', 'market', 'procurement', 'audit', 'raw',
    ]));
  });

  it('preserves every old tracetab deep link including execution', () => {
    for (const section of TRACE_SECTIONS) {
      for (const leaf of section.leaves) {
        expect(normalizeTraceLeaf(leaf)).toBe(leaf);
        expect(traceSectionForLeaf(leaf).id).toBe(section.id);
      }
    }
    expect(normalizeTraceLeaf('unknown')).toBe('events');
  });

  it('reserves agent authority for model-directed components', () => {
    expect(legacyComponentOntology('Recommendation_Agent')).toMatchObject({
      kind: 'model',
      authority: 'proposes',
    });
    expect(legacyComponentOntology('Procurement_Agent')).toMatchObject({
      kind: 'stage',
      authority: 'executes',
    });
  });

  it('describes market intelligence as evidence retrieval', () => {
    expect(legacyComponentOntology('Market_Intelligence_Agent')).toMatchObject({
      kind: 'connector',
      authority: 'retrieves',
    });
  });

  it('uses the later right-panel event when persistence preceded anchor construction', () => {
    const anchors = [{ title: 'Matched to your query', top_products: [{ sku: 'A' }] }];
    expect(resolveWhyAnchorSections(
      { right_panel: { anchor_sections: [] } },
      [
        {
          event_type: 'recommendation_result',
          payload: { right_panel_contract: { anchor_sections: [] } },
        },
        {
          event_type: 'right_panel_anchor_sections',
          payload: { right_panel_contract: { anchor_sections: anchors } },
        },
      ],
    )).toEqual(anchors);
  });

  it('compacts repeated stage execution without hiding authority boundaries', () => {
    expect(compactAuthorityPath([
      { authority: 'proposes' },
      { authority: 'authorizes' },
      { authority: 'executes' },
      { authority: 'executes' },
      { authority: 'executes' },
      { authority: 'authorizes' },
      { authority: 'presents' },
    ])).toBe('proposes -> authorizes -> executes (3 stages) -> authorizes -> presents');
  });

  it('normalizes a quarantined supplier response without exposing raw content', () => {
    expect(procurementQuarantineView(
      {
        state_json: {
          quarantine: {
            sender_domain: 'supplier.example',
            reason: 'inbound_security_review',
            security: {
              severity: 'critical',
              route: 'security_review',
              reasons: ['active_content', 'credential_request'],
            },
          },
        },
      },
      [{
        state: 'SUPPLIER_RESPONSE_QUARANTINED',
        event: 'supplier_response_quarantined',
        valid_from: '2026-07-27T14:20:00Z',
      }],
    )).toEqual({
      active: true,
      senderDomain: 'supplier.example',
      reason: 'inbound_security_review',
      severity: 'critical',
      route: 'security_review',
      securityReasons: ['active_content', 'credential_request'],
      timestamp: '2026-07-27T14:20:00Z',
    });
  });

  it('does not manufacture quarantine state when none was recorded', () => {
    expect(procurementQuarantineView({ state_json: {} }, [])).toMatchObject({ active: false });
  });

  it('derives persistent trust cues without converting missing evidence into confidence', () => {
    const strip = deriveTraceTrustStrip({
      nowMs: Date.parse('2026-07-31T00:00:00Z'),
      events: [{
        event_type: 'policy_gate',
        timestamp: '2026-07-30T23:00:00Z',
        payload: { status: 'authorized' },
      }],
      executionSteps: [{ authority: 'proposes' }, { authority: 'authorizes' }],
      evidence: { citations: [{ id: 'citation-1' }] },
      marketProjections: [{
        simulation_only: true,
        source_status: { sales: 'complete', inventory: 'complete' },
      }],
      hippographInsights: [{
        source_health: {
          status: 'degraded',
          degraded_sources: [{ source: 'public-index', reason: 'stale' }],
        },
      }],
    });

    expect(strip.authority.label).toBe('Platform authorized');
    expect(strip.execution.label).toBe('Not executed');
    expect(strip.freshness.status).toBe('good');
    expect(strip.completeness.label).toBe('Partial');
    expect(strip.uncertainty.label).toBe('1 concern');
    expect(strip.simulation.label).toBe('Simulation only');
  });

  it('labels blocked research as not assessed and materially uncertain', () => {
    const strip = deriveTraceTrustStrip({
      nowMs: Date.parse('2026-08-09T00:00:00Z'),
      events: [{
        event_type: 'official_research_rerank_completed',
        payload: {
          evidence_outcome: 'unresolved',
          official_claims: [], context_claims: [],
          evidence_ladder: [{ tier: 4, execution_status: 'degraded' }],
        },
      }],
      executionSteps: [], evidence: null, marketProjections: [], hippographInsights: [],
    });

    expect(strip.freshness.label).toBe('Not assessed');
    expect(strip.execution.label).toBe('Blocked');
    expect(strip.completeness.label).toBe('Not recorded');
    expect(strip.uncertainty.label).toBe('Material');
  });

  it('uses the retained original research event name after taxonomy normalization', () => {
    const strip = deriveTraceTrustStrip({
      nowMs: Date.parse('2026-08-09T00:00:00Z'),
      events: [{
        event_type: 'feedback_loop',
        payload: {
          _original_event_type: 'official_research_rerank_completed',
          evidence_outcome: 'context_only', official_claims: [],
          context_claims: [{ observed_at: '2026-08-08T23:00:00Z' }],
          evidence_ladder: [{ tier: 6, execution_status: 'activated' }],
        },
      }],
      executionSteps: [], evidence: null, marketProjections: [], hippographInsights: [],
    });

    expect(strip.freshness.label).toBe('Current');
    expect(strip.completeness.label).toBe('Partial');
    expect(strip.uncertainty.label).toBe('Material');
  });

  it('uses nested official claim observations for freshness', () => {
    const strip = deriveTraceTrustStrip({
      nowMs: Date.parse('2026-08-09T00:00:00Z'),
      events: [{
        event_type: 'official_research_rerank_completed',
        payload: {
          evidence_outcome: 'product_requirements',
          official_claims: [{ observed_at: '2026-08-08T23:00:00Z' }],
          context_claims: [], evidence_ladder: [],
        },
      }],
      executionSteps: [], evidence: null, marketProjections: [], hippographInsights: [],
    });

    expect(strip.freshness.label).toBe('Current');
    expect(strip.completeness.label).toBe('Complete');
    expect(strip.uncertainty.label).toBe('No material concern');
  });

  it('labels a receipted canonical official-origin fetch as completed', () => {
    const strip = deriveTraceTrustStrip({
      events: [{
        event_type: 'official_research_rerank_completed',
        payload: {
          evidence_outcome: 'product_requirements',
          official_claims: [{ observed_at: '2026-08-10T00:00:00Z' }],
          receipts: [{
            provider_kind: 'official_origin_fetch',
            execution_status: 'completed',
          }],
        },
      }],
      executionSteps: [], evidence: null, marketProjections: [], hippographInsights: [],
    });

    expect(strip.execution.label).toBe('Completed');
  });

  it('compacts raw event volume into state changed, prevented, and observed milestones', () => {
    const timeline = compactStateTimeline([
      { event_type: 'query_received', payload: { summary: 'Buyer request received' } },
      { event_type: 'pipeline_step', source_id: 'router', payload: {} },
      { event_type: 'quote_applied', payload: { from_state: 'draft', to_state: 'quoted' } },
      { event_type: 'supplier_response_quarantined', payload: { reason: 'active_content' } },
    ]);

    expect(timeline.map((item) => item.kind)).toEqual([
      'observed', 'changed', 'prevented',
    ]);
    expect(timeline[1]).toMatchObject({ fromState: 'draft', toState: 'quoted' });
    expect(timeline[2].detail).toMatch(/active content/i);
  });
});
