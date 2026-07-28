import { http } from './client';

export interface PartyIdentity {
  source: string;
  object_type: string;
  external_id: string;
  created_at?: string | null;
}

export interface AccountSummary {
  party_id: string;
  party_type: string;
  display_name?: string | null;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
  identities: PartyIdentity[];
  snapshot?: {
    measures: Record<string, any>;
    source_watermark?: string | null;
    rebuilt_at?: string | null;
  } | null;
}

export interface AccountTimelineEvent {
  id: string;
  event_type: string;
  event_class: string;
  occurred_at: string;
  authority: string;
  status?: string;
  confidence?: number;
  expires_at?: string;
  source_excerpt?: string;
  payload?: Record<string, any>;
  provenance?: Record<string, any>;
  counterparty_id?: string;
  execution_allowed?: boolean;
}

export interface AccountTimeline {
  party: AccountSummary & { authority: string };
  identities: PartyIdentity[];
  snapshot?: AccountSummary['snapshot'];
  timeline: AccountTimelineEvent[];
  authority_policy: Record<string, string>;
}

export interface IdentityProposal {
  id: string;
  decision_type: string;
  left_party_id: string;
  right_party_id: string;
  status: string;
  evidence: Record<string, any>;
  proposed_at: string;
  proposed_by?: string | null;
  resolved_at?: string | null;
  resolved_by?: string | null;
  resolution_note?: string | null;
  execution_allowed: false;
  human_review_required: true;
}

export const fetchAccounts = (query = '', limit = 100) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query.trim()) params.set('query', query.trim());
  return http<{ tenant_id: string; accounts: AccountSummary[] }>(
    `/api/v1/admin/accounts?${params.toString()}`,
  );
};

export const fetchAccountTimeline = (partyId: string, limit = 200) =>
  http<AccountTimeline>(
    `/api/v1/admin/accounts/${encodeURIComponent(partyId)}/timeline?limit=${limit}`,
  );

export const fetchIdentityProposals = (status = '') => {
  const params = new URLSearchParams({ limit: '100' });
  if (status) params.set('status', status);
  return http<{ tenant_id: string; proposals: IdentityProposal[] }>(
    `/api/v1/admin/accounts/identity/proposals?${params.toString()}`,
  );
};

export const createIdentityProposal = (body: {
  proposal_type: 'merge' | 'split';
  left_party_id: string;
  right_party_id: string;
  reason: string;
  evidence?: Record<string, any>;
}) => http<IdentityProposal & { message: string; authority: string }>(
  '/api/v1/admin/accounts/identity/proposals',
  { method: 'POST', body: JSON.stringify(body) },
);

export const resolveIdentityProposal = (
  proposalId: string,
  resolution: 'approved' | 'rejected',
  note: string,
) => http<IdentityProposal & { message: string; authority: string }>(
  `/api/v1/admin/accounts/identity/proposals/${encodeURIComponent(proposalId)}/resolve`,
  { method: 'POST', body: JSON.stringify({ resolution, note }) },
);
