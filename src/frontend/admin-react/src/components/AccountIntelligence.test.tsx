import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AccountIntelligence } from './AccountIntelligence';
import {
  createIdentityProposal,
  executeIdentityProposal,
  fetchAccounts,
  fetchAccountTimeline,
  fetchIdentityProposals,
  previewIdentityExecution,
  resolveIdentityProposal,
} from '../api';

vi.mock('../api', () => ({
  createIdentityProposal: vi.fn(),
  executeIdentityProposal: vi.fn(),
  fetchAccounts: vi.fn(),
  fetchAccountTimeline: vi.fn(),
  fetchIdentityProposals: vi.fn(),
  previewIdentityExecution: vi.fn(),
  resolveIdentityProposal: vi.fn(),
}));

const party = {
  party_id: 'party-left',
  party_type: 'buyer_account',
  display_name: 'Acme Buyer',
  status: 'active',
  updated_at: '2026-07-29T00:00:00Z',
  identities: [{
    source: 'csv', object_type: 'customer', external_id: 'buyer-hash-1',
  }],
  snapshot: null,
};
const proposal = {
  id: 'proposal-1',
  decision_type: 'merge_proposal',
  left_party_id: 'party-left',
  right_party_id: 'party-right',
  status: 'proposed',
  evidence: { operator_reason: 'same registered business identifier' },
  proposed_at: '2026-07-29T00:00:00Z',
  proposed_by: 'operator-1',
  execution_allowed: false as const,
  human_review_required: true as const,
};

describe('AccountIntelligence', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(fetchAccounts).mockResolvedValue({ tenant_id: 'default', accounts: [party] });
    vi.mocked(fetchIdentityProposals).mockResolvedValue({
      tenant_id: 'default', proposals: [proposal],
    });
    vi.mocked(fetchAccountTimeline).mockResolvedValue({
      party: { ...party, authority: 'authoritative_party_record' },
      identities: party.identities,
      snapshot: null,
      timeline: [{
        id: 'obs-1',
        event_type: 'budget',
        event_class: 'conversation_observation',
        occurred_at: '2026-07-29T00:00:00Z',
        authority: 'observation_only',
        confidence: 0.8,
        expires_at: '2026-08-28T00:00:00Z',
        source_excerpt: 'budget AUD 5000',
        payload: { amount: 5000, currency: 'AUD' },
        provenance: { source_message_id: 'message-1' },
      }],
      authority_policy: {
        party_record: 'authoritative',
        conversation_facts: 'observation_only',
        identity_resolution: 'proposal_only_human_review',
      },
    } as any);
    vi.mocked(createIdentityProposal).mockResolvedValue({
      ...proposal,
      message: 'Recorded for human review; no Party records were changed.',
      authority: 'proposal_only',
    });
    vi.mocked(resolveIdentityProposal).mockResolvedValue({
      ...proposal,
      status: 'approved',
      message: 'Disposition recorded; execution remains a separate manual workflow.',
      authority: 'human_disposition_only',
    });
    vi.mocked(previewIdentityExecution).mockResolvedValue({
      proposal_id: proposal.id,
      decision_type: proposal.decision_type,
      status: 'approved',
      source_party_id: proposal.left_party_id,
      target_party_id: proposal.right_party_id,
      canonical_source_party_id: proposal.left_party_id,
      canonical_target_party_id: proposal.right_party_id,
      graph_version: 0,
      impact_counts: { account_activities: 2, external_identities: 1 },
      conflicts: [],
      executable: true,
      execution_policy: {
        moves_historical_records: false,
        append_only_redirect: true,
        separate_owner_execution_required: true,
        proposal_creator_may_execute: false,
      },
    });
    vi.mocked(executeIdentityProposal).mockResolvedValue({
      event_id: 'redirect-event-1',
      event_type: 'merge_redirect',
      graph_version: 1,
      historical_records_moved: false,
      message: 'Canonical resolution changed; historical Party records were not moved.',
      authority: 'owner_executed_append_only_redirect',
    });
  });

  it('separates authoritative Party facts from expiring conversation observations', async () => {
    render(<AccountIntelligence role="merchant" />);
    expect(await screen.findByText('Acme Buyer')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Acme Buyer'));

    expect(await screen.findByText(/Authority: AUTHORITATIVE PARTY RECORD/)).toBeInTheDocument();
    const event = await screen.findByTestId('account-timeline-event');
    expect(event).toHaveTextContent('conversation observation');
    expect(event).toHaveTextContent('observation only');
    expect(screen.getByTestId('account-authority-policy')).toHaveTextContent(
      'Conversation facts remain expiring observations',
    );
  });

  it('records and resolves proposals while keeping execution separate', async () => {
    render(<AccountIntelligence role="owner" />);
    fireEvent.click(await screen.findByText('Acme Buyer'));
    fireEvent.change(await screen.findByLabelText('Counterparty Party ID'), {
      target: { value: 'party-right' },
    });
    fireEvent.change(screen.getByLabelText('Proposal evidence'), {
      target: { value: 'same business identifier' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Record proposal for human review' }));
    await waitFor(() => expect(createIdentityProposal).toHaveBeenCalled());
    expect(await screen.findByText(/no Party records were changed/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Resolution note'), {
      target: { value: 'reviewed by account owner' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Approve for separate manual execution' }));
    await waitFor(() => expect(resolveIdentityProposal).toHaveBeenCalledWith(
      'proposal-1', 'approved', 'reviewed by account owner',
    ));
    expect(screen.getByTestId('identity-proposal')).toHaveTextContent('execution: not allowed');
  });

  it('previews blast radius before executing an approved append-only redirect', async () => {
    vi.mocked(fetchIdentityProposals).mockResolvedValue({
      tenant_id: 'default',
      proposals: [{ ...proposal, status: 'approved' }],
    });
    render(<AccountIntelligence role="owner" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Preview redirect impact' }));
    const impact = await screen.findByTestId('identity-execution-impact');
    expect(impact).toHaveTextContent('historical records moved: never');
    expect(impact).toHaveTextContent('account activities 2');

    fireEvent.change(screen.getByLabelText('Identity execution note'), {
      target: { value: 'owner reviewed impact and redirect direction' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Execute append-only redirect' }));

    await waitFor(() => expect(executeIdentityProposal).toHaveBeenCalledWith(
      proposal.id,
      0,
      `identity-execution:${proposal.id}:0`,
      'owner reviewed impact and redirect direction',
    ));
    expect(await screen.findByText(/historical Party records were not moved/i)).toBeInTheDocument();
  });
});
