import { useState } from 'react';

const secondaryActionStyle = {
  background: '#fff', color: '#c2410c', border: '1px solid #f15a0a',
  borderRadius: 6, padding: '7px 11px', fontWeight: 700,
} as const;

export type AmbiguityExploration = {
  schema_version: 'ambiguity-exploration-v1';
  case_id?: string;
  trace_id?: string;
  retained_purpose: string;
  status: 'provisional' | 'researched' | 'context_only' | 'unresolved';
  interpretations: { hypothesis_id?: string; label?: string; confidence?: number }[];
  next_question?: { text?: string; question?: string } | null;
  execution: string;
  evidence: string;
  decision: string;
  cart_authority: string;
  provider_accounting: { external_calls: number; paid_calls: number };
  interpretation_job?: {
    job_id?: string | null; case_revision?: number; status?: string;
    authority?: string; receipt?: Record<string, unknown> | null;
  } | null;
  research_plan_id?: string | null;
  ambiguity_objects?: { ambiguity_id: string }[];
  research_obligations?: {
    obligation_id: string;
    resolution_owner: 'catalog' | 'research' | 'buyer' | 'computation' | 'supplier' | 'tenant_policy' | 'human';
    status: string;
  }[];
  source_candidate_ids?: string[];
  publisher_candidates?: {
    candidate_id?: string; candidate_version?: number;
    url: string; domain: string; title: string; discovery_only: boolean; authority: string;
    status?: string; approval_scope?: string | null;
  }[];
  identity_candidates?: {
    requested_name?: string; resolved_name?: string; source?: string; source_url?: string;
    confidence?: number; status?: string; requirements_status?: string;
  }[];
  canonical_truth?: Record<string, unknown> | null;
  source_intake_certificate?: {
    resolution?: { status?: string };
    security?: {
      link_assessment?: {
        security_status?: string;
        relevance?: string;
        recommended_use?: string;
      };
    };
  } | null;
};

type Props = {
  exploration: AmbiguityExploration;
  onResearch: (refreshAuthorized?: boolean) => void;
  onUpload: () => void;
  onEnterSpecifications: () => void;
  onSubmitSpecifications?: (text: string) => Promise<void>;
  onResolveEvidenceSource?: (
    hint: { source_url?: string; vendor_name?: string },
    researchAuthorized: boolean,
  ) => Promise<any>;
  onApprovePublisherCandidate?: (
    candidate: NonNullable<AmbiguityExploration['publisher_candidates']>[number],
  ) => Promise<void>;
  autoResearchEnabled?: boolean;
};

export default function AmbiguityExplorationPanel({
  exploration, onResearch, onUpload, onEnterSpecifications, onResolveEvidenceSource,
  onSubmitSpecifications, onApprovePublisherCandidate, autoResearchEnabled = false,
}: Props) {
  const [showSourceResolver, setShowSourceResolver] = useState(false);
  const [sourceHint, setSourceHint] = useState('');
  const [sourceResolution, setSourceResolution] = useState<any>(null);
  const [sourceBusy, setSourceBusy] = useState(false);
  const [showManualSpecifications, setShowManualSpecifications] = useState(false);
  const [manualSpecifications, setManualSpecifications] = useState('');
  const [manualStatus, setManualStatus] = useState('');
  const [manualBusy, setManualBusy] = useState(false);
  const [approvingCandidate, setApprovingCandidate] = useState<string | null>(null);
  const [candidateStatus, setCandidateStatus] = useState('');
  const openWorldDiscovery = (exploration.source_candidate_ids?.length || 0) === 0;
  const question = exploration.next_question?.text || exploration.next_question?.question;
  const buyerStatus = String(exploration.evidence || '').includes('pending_policy_review')
    ? 'Canonical requirements were fetched and extracted; claims await independent policy review, so product fit remains provisional.'
    : exploration.status === 'researched'
      ? 'Official requirements compiled; unresolved gaps remain conditional.'
    : exploration.status === 'context_only'
      ? 'Research found context, but no authoritative product requirements.'
      : exploration.status === 'unresolved'
        ? 'No approved requirement source was established; recommendations remain provisional.'
        : autoResearchEnabled
          ? 'Approved external research is running; recommendations remain provisional.'
          : 'External research has not produced evidence; provide an official link, upload, or typed requirements.';
  const resolveSource = async (researchAuthorized: boolean) => {
    if (!onResolveEvidenceSource || !sourceHint.trim() || sourceBusy) return;
    setSourceBusy(true);
    try {
      const value = sourceHint.trim();
      const hint = /^https:\/\//i.test(value) ? { source_url: value } : { vendor_name: value };
      setSourceResolution(await onResolveEvidenceSource(hint, researchAuthorized));
    } catch (error) {
      setSourceResolution({
        status: 'error', reason: error instanceof Error ? error.message : 'Source resolution failed.',
      });
    } finally {
      setSourceBusy(false);
    }
  };
  return (
    <section data-testid="ambiguity-exploration" style={{ margin: 12, padding: 12, border: '1px solid #93c5fd', borderRadius: 10, background: '#f8fbff' }}>
      <div data-testid="buyer-research-status" style={{ color: '#1e293b' }}>
        <strong>Research status:</strong> {buyerStatus}
      </div>
      {exploration.identity_candidates?.length ? (
        <div data-testid="official-identity-candidate" style={{ marginTop: 9, padding: 9, border: '1px solid #93c5fd', borderRadius: 8, background: '#fff' }}>
          <strong>Likely official match:</strong>{' '}
          {exploration.identity_candidates[0].source_url ? (
            <a href={exploration.identity_candidates[0].source_url} target="_blank" rel="noreferrer">
              {exploration.identity_candidates[0].resolved_name}
            </a>
          ) : exploration.identity_candidates[0].resolved_name}
          <div style={{ marginTop: 3, fontSize: 12, color: '#475569' }}>
            Official identity candidate only; material hardware requirements are not yet published or accepted.
          </div>
        </div>
      ) : null}
      {question && <div data-testid="high-information-question" style={{ marginTop: 10, padding: 9, borderRadius: 7, background: '#fff' }}><strong>To narrow it down:</strong> {question}</div>}
      {exploration.publisher_candidates && exploration.publisher_candidates.length > 0 && (
        <div data-testid="publisher-candidates" style={{ marginTop: 9, padding: 9, border: '1px solid #fdba74', borderRadius: 8 }}>
          <strong>Possible publisher sources — ownership not yet verified</strong>
          <ul style={{ margin: '5px 0', paddingLeft: 20 }}>
            {exploration.publisher_candidates.slice(0, 5).map((candidate) => (
              <li key={candidate.url}>
                <a href={candidate.url} target="_blank" rel="noreferrer">{candidate.title || candidate.domain}</a>
                {' '}({candidate.domain})
                {onApprovePublisherCandidate && candidate.candidate_id && (
                  <button
                    type="button"
                    disabled={Boolean(approvingCandidate)}
                    onClick={() => {
                      setApprovingCandidate(candidate.candidate_id);
                      setCandidateStatus('');
                      void onApprovePublisherCandidate(candidate)
                        .then(() => setCandidateStatus(
                          'The exact origin was fetched. Review its extracted claims before they affect fit.',
                        ))
                        .catch((error) => setCandidateStatus(
                          error instanceof Error ? error.message : 'Publisher research failed.',
                        ))
                        .finally(() => setApprovingCandidate(null));
                    }}
                    style={{ ...secondaryActionStyle, marginLeft: 7, padding: '4px 8px' }}
                  >
                    {approvingCandidate === candidate.candidate_id
                      ? 'Fetching exact origin…' : 'Use for this case'}
                  </button>
                )}
              </li>
            ))}
          </ul>
          <div style={{ fontSize: 12 }}>
            Case-only approval fetches this exact origin. It does not enroll the publisher globally or authorize a purchase.
          </div>
          {candidateStatus && <div role="status" style={{ marginTop: 6, fontSize: 12 }}>{candidateStatus}</div>}
        </div>
      )}
      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 10 }}>
        {exploration.status === 'provisional' && Boolean(exploration.research_plan_id) && !autoResearchEnabled && (
          <button type="button" onClick={() => onResearch(false)} style={{ background: '#f15a0a', color: '#fff', border: 0, borderRadius: 6, padding: '7px 11px', fontWeight: 700 }}>
            {openWorldDiscovery ? 'Discover official sources' : 'Research approved sources'}
          </button>
        )}
        {exploration.status === 'unresolved'
          && !String(exploration.evidence || '').includes('pending_policy_review')
          && Boolean(exploration.research_plan_id) && (
          <button type="button" onClick={() => onResearch(true)} style={{ background: '#f15a0a', color: '#fff', border: 0, borderRadius: 6, padding: '7px 11px', fontWeight: 700 }}>
            {openWorldDiscovery ? 'Refresh source discovery' : 'Retry approved research'}
          </button>
        )}
        {!exploration.research_plan_id && (
          <span data-testid="research-plan-unavailable" style={{ fontSize: 12, color: '#9a3412', alignSelf: 'center' }}>
            No governed research plan is available; upload, link, or enter requirements instead.
          </span>
        )}
        <button type="button" onClick={onUpload} style={secondaryActionStyle}>Upload requirements</button>
        {onResolveEvidenceSource && (
          <button type="button" onClick={() => setShowSourceResolver((value) => !value)} style={secondaryActionStyle}>Use official link or vendor</button>
        )}
        <button type="button" onClick={() => {
          setShowManualSpecifications((value) => !value);
          onEnterSpecifications();
        }} style={secondaryActionStyle}>Enter specifications</button>
        <span style={{ fontSize: 12, alignSelf: 'center', color: '#475569' }}>No product is qualified until the material gap is resolved.</span>
      </div>
      {showManualSpecifications && onSubmitSpecifications && (
        <div data-testid="manual-requirement-entry" style={{ marginTop: 10, border: '1px solid #cbd5e1', borderRadius: 8, padding: 9 }}>
          <label htmlFor="manual-requirements" style={{ display: 'block', fontWeight: 700 }}>
            Enter explicit requirements
          </label>
          <div style={{ fontSize: 12, color: '#475569', margin: '3px 0 7px' }}>
            These become provisional buyer claims for review; they do not qualify a product automatically.
          </div>
          <textarea
            id="manual-requirements"
            aria-label="Manual specifications"
            value={manualSpecifications}
            onChange={(event) => setManualSpecifications(event.target.value)}
            placeholder="RAM 32GB minimum; 1TB NVMe; Windows 11 Pro recommended"
            rows={4}
            style={{ width: '100%', padding: 7, border: '1px solid #94a3b8', borderRadius: 6 }}
          />
          <button
            type="button"
            disabled={manualBusy || manualSpecifications.trim().length < 3}
            onClick={() => {
              setManualBusy(true);
              setManualStatus('');
              void onSubmitSpecifications(manualSpecifications.trim())
                .then(() => setManualStatus('Specifications extracted for review.'))
                .catch((error) => setManualStatus(error instanceof Error ? error.message : 'Could not extract specifications.'))
                .finally(() => setManualBusy(false));
            }}
            style={{ ...secondaryActionStyle, marginTop: 7 }}
          >
            Review extracted requirements
          </button>
          {manualStatus && <div role="status" style={{ marginTop: 6, fontSize: 12 }}>{manualStatus}</div>}
        </div>
      )}
      {showSourceResolver && onResolveEvidenceSource && (
        <div data-testid="buyer-evidence-source-resolver" style={{ marginTop: 10, border: '1px solid #cbd5e1', borderRadius: 8, padding: 9 }}>
          <label htmlFor="buyer-evidence-source" style={{ display: 'block', fontWeight: 700 }}>
            Official requirements URL or named vendor
          </label>
          <div style={{ fontSize: 12, color: '#475569', margin: '3px 0 7px' }}>
            Checking the registry is local and free. Fetching the reviewed canonical page requires your next confirmation.
          </div>
          <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>
            <input
              id="buyer-evidence-source"
              value={sourceHint}
              onChange={(event) => { setSourceHint(event.target.value); setSourceResolution(null); }}
              placeholder="https://docs.vendor.example/... or Autodesk"
              style={{ flex: '1 1 300px', minWidth: 220, padding: 7, border: '1px solid #94a3b8', borderRadius: 6 }}
            />
            <button type="button" disabled={sourceBusy || !sourceHint.trim()} onClick={() => { void resolveSource(false); }} style={secondaryActionStyle}>
              Check source
            </button>
          </div>
          {sourceResolution && (
            <div role="status" style={{ marginTop: 8, fontSize: 12 }}>
              <strong>{String(sourceResolution.status || 'unknown').replaceAll('_', ' ')}</strong>
              {sourceResolution.security_status ? (
                <div data-testid="source-safety-status" style={{ marginTop: 4, color: sourceResolution.security_status === 'blocked' ? '#b91c1c' : '#475569' }}>
                  Link safety: <strong>{String(sourceResolution.security_status).replaceAll('_', ' ')}</strong>. The submitted path is never fetched directly; only the reviewed canonical origin can be fetched after authorization.
                </div>
              ) : null}
              {sourceResolution.reason ? ` — ${String(sourceResolution.reason).replaceAll('_', ' ')}` : ''}
              {Array.isArray(sourceResolution.candidates) && sourceResolution.candidates.length > 0 && (
                <ul style={{ margin: '5px 0', paddingLeft: 20 }}>
                  {sourceResolution.candidates.map((candidate: any) => (
                    <li key={candidate.source_id}>{candidate.publisher}: {candidate.canonical_url}</li>
                  ))}
                </ul>
              )}
              {sourceResolution.status === 'resolved' && sourceResolution.research_status !== 'claims_pending_review' && (
                <button type="button" disabled={sourceBusy} onClick={() => { void resolveSource(true); }} style={{ marginTop: 5, background: '#f15a0a', color: '#fff', border: 0, borderRadius: 6, padding: '7px 11px', fontWeight: 700 }}>
                  Research matched canonical source
                </button>
              )}
              {sourceResolution.research_status === 'claims_pending_review' && (
                <div data-testid="source-claims-pending-review" style={{ marginTop: 5, color: '#92400e' }}>
                  The canonical source was fetched and {sourceResolution.provisional_claim_count || 0} cited claims were extracted. Review them in the conversation; they remain provisional until independent policy approval.
                </div>
              )}
            </div>
          )}
        </div>
      )}
      <details data-testid="buyer-research-proof" style={{ marginTop: 9, fontSize: 11 }}>
        <summary>View research proof</summary>
        <div style={{ marginTop: 7 }}><strong>Retained purpose:</strong> {exploration.retained_purpose}</div>
        {exploration.interpretations?.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <strong>Why research is needed</strong>
            <ul>{exploration.interpretations.map((item, index) => (
              <li key={item.hypothesis_id || index}>{item.label || item.hypothesis_id || `Interpretation ${index + 1}`}</li>
            ))}</ul>
          </div>
        )}
        {exploration.research_obligations?.length ? (
          <div data-testid="research-resolution-owners" style={{ marginTop: 5 }}>
            {exploration.research_obligations.map((item) => (
              <div key={item.obligation_id}>{item.obligation_id}: {item.resolution_owner} ({item.status})</div>
            ))}
          </div>
        ) : null}
        <div data-testid="ambiguity-accounting" style={{ marginTop: 5 }}>
        {exploration.interpretation_job?.job_id ? (
          <div data-testid="interpretation-job-receipt">
            Interpretation refinement: {exploration.interpretation_job.status}
            {' · '}case revision {exploration.interpretation_job.case_revision}
            {' · '}authority {exploration.interpretation_job.authority || 'none'}
          </div>
        ) : null}
        Execution: {exploration.execution} · Evidence: {exploration.evidence} · Decision: {exploration.decision}
        {' · '}External calls: {exploration.provider_accounting.external_calls}
        {' · '}Paid calls: {exploration.provider_accounting.paid_calls}
        {' · '}Cart authority: {exploration.cart_authority}
        </div>
      </details>
    </section>
  );
}
