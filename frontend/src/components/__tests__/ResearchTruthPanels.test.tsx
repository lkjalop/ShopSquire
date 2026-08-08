import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import AmbiguityExplorationPanel from '../AmbiguityExplorationPanel';
import ProductShelvesPanel from '../ProductShelvesPanel';

describe('research truth panels', () => {
  it('renders context-only research without offering an accidental repeat', () => {
    render(<AmbiguityExplorationPanel
      exploration={{
        schema_version: 'ambiguity-exploration-v1',
        retained_purpose: 'Predictive maintenance digital twin',
        status: 'context_only',
        interpretations: [],
        next_question: { text: 'Which named simulator and version will run locally?' },
        execution: 'live_discovery_and_official_fetch_completed',
        evidence: 'authoritative_context_only',
        decision: 'provisional_exploration_only',
        cart_authority: 'none',
        provider_accounting: { external_calls: 2, paid_calls: 0 },
      }}
      onResearch={vi.fn()}
      onUpload={vi.fn()}
      onEnterSpecifications={vi.fn()}
    />);

    expect(screen.getByText(/no authoritative product requirements/i)).toBeTruthy();
    expect(screen.getByText(/Which named simulator/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Research approved sources' })).toBeNull();
  });

  it('keeps context-only shelves provisional and labels conditional actions for review', () => {
    render(<ProductShelvesPanel
      projection={{
        schema_version: 'product-shelves-v1', evidence_status: 'context_only',
        official_claim_count: 0, context_claim_count: 2, research_delta: [],
        shelves: [{
          shelf_id: 'shared', scope_label: 'Shared fit', budget_band: 'best',
          remaining_count: 0, next_page: [], initial: [{
            identity_key: 'pc-1', title: 'Conditional workstation',
            price_cents: 300000, currency: 'AUD', fit_status: 'conditional',
            relevance_score: 0.5, product: { sku: 'WS-1', identifier: 'MPN-1' },
            unknowns: ['named simulator requirement'], freshness_status: 'unknown',
          }],
        }],
      }}
      onPropose={vi.fn()}
    />);

    expect(screen.getByText(/no authoritative product requirements/i)).toBeTruthy();
    expect(screen.getByText(/did not authorize a verified rerank/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Review option' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Propose cart change' })).toBeNull();
  });
});
