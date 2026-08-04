import React, { useCallback, useEffect, useState } from 'react';
import {
  createIdentityProposal,
  executeIdentityProposal,
  fetchAccounts,
  fetchAccountTimeline,
  fetchIdentityProposals,
  previewIdentityExecution,
  resolveIdentityProposal,
  type AccountSummary,
  type AccountTimeline,
  type IdentityExecutionImpact,
  type IdentityProposal,
} from '../api';


const label = (value: string | undefined | null) =>
  String(value || 'not reported').replace(/_/g, ' ');

export function AccountIntelligence({ role }: { role: 'merchant' | 'owner' | 'developer' }) {
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [selected, setSelected] = useState('');
  const [timeline, setTimeline] = useState<AccountTimeline | null>(null);
  const [proposals, setProposals] = useState<IdentityProposal[]>([]);
  const [query, setQuery] = useState('');
  const [proposalType, setProposalType] = useState<'merge' | 'split'>('merge');
  const [counterpartyId, setCounterpartyId] = useState('');
  const [reason, setReason] = useState('');
  const [resolutionNote, setResolutionNote] = useState('');
  const [executionNote, setExecutionNote] = useState('');
  const [executionImpact, setExecutionImpact] = useState<Record<string, IdentityExecutionImpact>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadAccounts = useCallback(async (search: string) => {
    try {
      const result = await fetchAccounts(search);
      setAccounts(result.accounts || []);
      setError('');
    } catch (err: any) {
      setError(err?.message || 'Account list is unavailable.');
    }
  }, []);
  const loadProposals = useCallback(async () => {
    try {
      const result = await fetchIdentityProposals();
      setProposals(result.proposals || []);
    } catch (err: any) {
      setError(err?.message || 'Identity proposals are unavailable.');
    }
  }, []);
  const loadTimeline = useCallback(async (partyId: string) => {
    if (!partyId) return;
    try {
      setTimeline(await fetchAccountTimeline(partyId));
      setError('');
    } catch (err: any) {
      setTimeline(null);
      setError(err?.message || 'Account timeline is unavailable.');
    }
  }, []);

  useEffect(() => {
    void loadAccounts('');
    void loadProposals();
  }, [loadAccounts, loadProposals]);
  useEffect(() => { if (selected) void loadTimeline(selected); }, [selected, loadTimeline]);

  const propose = async () => {
    if (!selected || !counterpartyId.trim() || reason.trim().length < 3) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await createIdentityProposal({
        proposal_type: proposalType,
        left_party_id: selected,
        right_party_id: counterpartyId.trim(),
        reason: reason.trim(),
      });
      setNotice(result.message);
      setReason('');
      setCounterpartyId('');
      await Promise.all([loadProposals(), loadTimeline(selected)]);
    } catch (err: any) {
      setError(err?.message || 'Could not record identity proposal.');
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (proposal: IdentityProposal, resolution: 'approved' | 'rejected') => {
    if (resolutionNote.trim().length < 3) {
      setError('A resolution note of at least three characters is required.');
      return;
    }
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await resolveIdentityProposal(
        proposal.id, resolution, resolutionNote.trim(),
      );
      setNotice(result.message);
      setResolutionNote('');
      await Promise.all([loadProposals(), selected ? loadTimeline(selected) : Promise.resolve()]);
    } catch (err: any) {
      setError(err?.message || 'Could not resolve identity proposal.');
    } finally {
      setBusy(false);
    }
  };

  const previewExecution = async (proposal: IdentityProposal) => {
    setBusy(true); setError(''); setNotice('');
    try {
      const impact = await previewIdentityExecution(proposal.id);
      setExecutionImpact((current) => ({ ...current, [proposal.id]: impact }));
    } catch (err: any) {
      setError(err?.message || 'Could not calculate identity execution impact.');
    } finally {
      setBusy(false);
    }
  };

  const execute = async (proposal: IdentityProposal) => {
    const impact = executionImpact[proposal.id];
    if (!impact?.executable || executionNote.trim().length < 3) {
      setError('Preview an executable change and provide an execution note.');
      return;
    }
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await executeIdentityProposal(
        proposal.id,
        impact.graph_version,
        `identity-execution:${proposal.id}:${impact.graph_version}`,
        executionNote.trim(),
      );
      setNotice(result.message);
      setExecutionNote('');
      setExecutionImpact((current) => {
        const next = { ...current };
        delete next[proposal.id];
        return next;
      });
      await Promise.all([
        loadProposals(),
        loadAccounts(query),
        selected ? loadTimeline(selected) : Promise.resolve(),
      ]);
    } catch (err: any) {
      setError(err?.message || 'Could not execute identity redirect.');
    } finally {
      setBusy(false);
    }
  };

  const account = timeline?.party;
  return (
    <div data-testid="account-intelligence">
      <div className="callout" data-testid="account-authority-policy" style={{ marginBottom: 12 }}>
        <strong>Authority boundary:</strong> Party records stay authoritative. Conversation facts remain
        expiring observations. Approval and execution are separate. Execution creates an append-only,
        reversible canonical redirect and never moves historical records.
      </div>
      {error && <p role="alert" style={{ color: 'crimson' }}>{error}</p>}
      {notice && <p role="status" style={{ color: '#166534' }}>{notice}</p>}

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        <aside style={{ flex: '0 0 330px' }}>
          <form onSubmit={(event) => { event.preventDefault(); void loadAccounts(query); }}
                style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
            <input aria-label="Search accounts" value={query} onChange={(event) => setQuery(event.target.value)}
                   placeholder="name · Party ID · exact source ID" style={{ flex: 1 }} />
            <button type="submit">Search</button>
          </form>
          <div className="list" data-testid="account-list">
            {accounts.map((item) => (
              <button key={item.party_id} onClick={() => setSelected(item.party_id)}
                      className={selected === item.party_id ? 'active' : ''}
                      style={{ textAlign: 'left', padding: 8 }}>
                <strong>{item.display_name || item.party_id}</strong>
                <div style={{ fontSize: 12 }}>{label(item.party_type)} · {item.status}</div>
                <div style={{ fontSize: 11, opacity: 0.7 }}>{item.party_id}</div>
              </button>
            ))}
            {!accounts.length && <div className="page-sub">No tenant-scoped Party records found.</div>}
          </div>
        </aside>

        <section style={{ minWidth: 0, flex: 1 }}>
          {!account && <div className="page-sub">Select an account to inspect its evidence timeline.</div>}
          {account && (
            <>
              <div className="card">
                <h3 style={{ marginTop: 0 }}>{account.display_name || account.party_id}</h3>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <span className="badge">Authority: AUTHORITATIVE PARTY RECORD</span>
                  <span className="badge">Type: {label(account.party_type).toUpperCase()}</span>
                  <span className="badge">
                    Freshness: {timeline?.snapshot?.source_watermark || account.updated_at || 'NOT REPORTED'}
                  </span>
                </div>
                <div style={{ marginTop: 8 }}>
                  {(timeline?.identities || []).map((identity) => (
                    <div key={`${identity.source}-${identity.object_type}-${identity.external_id}`}>
                      <code>{identity.source}:{identity.object_type}</code> → {identity.external_id}
                    </div>
                  ))}
                  {!timeline?.identities.length && <span className="page-sub">No exact external identities.</span>}
                </div>
                {timeline?.snapshot && (
                  <details style={{ marginTop: 8 }}>
                    <summary>Rebuildable account measures</summary>
                    <pre className="panel">{JSON.stringify(timeline.snapshot.measures, null, 2)}</pre>
                  </details>
                )}
              </div>

              <div className="card" style={{ marginTop: 12 }}>
                <h3 style={{ marginTop: 0 }}>Evidence timeline</h3>
                {(timeline?.timeline || []).map((event) => (
                  <details key={`${event.event_class}-${event.id}`}
                           data-testid="account-timeline-event"
                           style={{ borderTop: '1px solid #e5e7eb', padding: '8px 0' }}>
                    <summary>
                      <strong>{label(event.event_type)}</strong>
                      {' · '}{label(event.event_class)}
                      {' · '}{event.occurred_at}
                      {' · '}<span className="badge">{label(event.authority)}</span>
                      {event.status && <> · {label(event.status)}</>}
                    </summary>
                    {event.confidence != null && <div>Confidence: {(event.confidence * 100).toFixed(0)}%</div>}
                    {event.expires_at && <div>Expires: {event.expires_at}</div>}
                    {event.source_excerpt && <blockquote>{event.source_excerpt}</blockquote>}
                    {event.counterparty_id && <div>Counterparty: <code>{event.counterparty_id}</code></div>}
                    <pre className="panel">{JSON.stringify({
                      payload: event.payload,
                      provenance: event.provenance,
                    }, null, 2)}</pre>
                  </details>
                ))}
                {!timeline?.timeline.length && <div className="page-sub">No activities or observations recorded.</div>}
              </div>

              <div className="card" style={{ marginTop: 12 }}>
                <h3 style={{ marginTop: 0 }}>Propose identity review</h3>
                <p className="page-sub">
                  This records evidence for a human. It never moves activities, identities, pricing or credit terms.
                </p>
                <div style={{ display: 'grid', gap: 8 }}>
                  <select aria-label="Proposal type" value={proposalType}
                          onChange={(event) => setProposalType(event.target.value as 'merge' | 'split')}>
                    <option value="merge">Possible duplicate · merge proposal</option>
                    <option value="split">Incorrect association · split proposal</option>
                  </select>
                  <input aria-label="Counterparty Party ID" value={counterpartyId}
                         onChange={(event) => setCounterpartyId(event.target.value)}
                         placeholder="Existing tenant-scoped Party ID" />
                  <textarea aria-label="Proposal evidence" value={reason}
                            onChange={(event) => setReason(event.target.value)}
                            placeholder="Why should a human review this identity relationship?" />
                  <button disabled={busy || reason.trim().length < 3 || !counterpartyId.trim()}
                          onClick={() => void propose()}>
                    Record proposal for human review
                  </button>
                </div>
              </div>
            </>
          )}

          <div className="card" style={{ marginTop: 12 }}>
            <h3 style={{ marginTop: 0 }}>Identity review queue</h3>
            {role === 'owner' && (
              <input aria-label="Resolution note" value={resolutionNote}
                     onChange={(event) => setResolutionNote(event.target.value)}
                     placeholder="Required owner disposition note" style={{ width: '100%', marginBottom: 8 }} />
            )}
            {proposals.map((proposal) => (
              <div key={proposal.id} data-testid="identity-proposal"
                   style={{ borderTop: '1px solid #e5e7eb', padding: '8px 0' }}>
                <strong>{label(proposal.decision_type)}</strong> · {proposal.status}
                <div><code>{proposal.left_party_id}</code> ↔ <code>{proposal.right_party_id}</code></div>
                <div className="page-sub">
                  Proposed {proposal.proposed_at} by {proposal.proposed_by || 'unknown'}
                  {' · '}execution: {proposal.status === 'approved' ? 'separate owner workflow' : 'not allowed'}
                </div>
                <details><summary>Evidence</summary><pre className="panel">{JSON.stringify(proposal.evidence, null, 2)}</pre></details>
                {role === 'owner' && proposal.status === 'proposed' && (
                  <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                    <button disabled={busy} onClick={() => void resolve(proposal, 'approved')}>
                      Approve for separate manual execution
                    </button>
                    <button disabled={busy} onClick={() => void resolve(proposal, 'rejected')}>
                      Reject proposal
                    </button>
                  </div>
                )}
                {role === 'owner' && proposal.status === 'approved' && (
                  <div style={{ marginTop: 8 }}>
                    <button disabled={busy} onClick={() => void previewExecution(proposal)}>
                      Preview redirect impact
                    </button>
                    {executionImpact[proposal.id] && (
                      <div data-testid="identity-execution-impact" className="callout" style={{ marginTop: 8 }}>
                        <div>
                          Version {executionImpact[proposal.id].graph_version} ·
                          {' '}historical records moved: never · append-only redirect: yes
                        </div>
                        <div>
                          Impact counts:{' '}
                          {Object.entries(executionImpact[proposal.id].impact_counts)
                            .map(([name, count]) => `${label(name)} ${count}`)
                            .join(' · ')}
                        </div>
                        {executionImpact[proposal.id].conflicts.length > 0 && (
                          <div>
                            Conflicts: {executionImpact[proposal.id].conflicts.map(label).join('; ')}
                          </div>
                        )}
                        <input
                          aria-label="Identity execution note"
                          value={executionNote}
                          onChange={(event) => setExecutionNote(event.target.value)}
                          placeholder="Why should this approved redirect execute now?"
                          style={{ width: '100%', marginTop: 6 }}
                        />
                        <button
                          disabled={
                            busy
                            || !executionImpact[proposal.id].executable
                            || executionNote.trim().length < 3
                          }
                          onClick={() => void execute(proposal)}
                          style={{ marginTop: 6 }}
                        >
                          Execute append-only redirect
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            {!proposals.length && <div className="page-sub">No identity proposals.</div>}
          </div>
        </section>
      </div>
    </div>
  );
}

export default AccountIntelligence;
