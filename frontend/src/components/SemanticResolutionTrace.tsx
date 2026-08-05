import React from 'react';

type Props = {
  resolution?: any;
  evidence?: any;
  alignment?: any;
  caseObligations?: any[];
};

const label = (value: unknown) => String(value || '').replace(/_/g, ' ');

const sourceTime = (value: unknown) => {
  if (!value) return 'time not recorded';
  const numeric = Number(value);
  const date = Number.isFinite(numeric) ? new Date(numeric * 1000) : new Date(String(value));
  return Number.isNaN(date.getTime()) ? 'time not recorded' : date.toISOString();
};

export default function SemanticResolutionTrace({ resolution, evidence, alignment, caseObligations = [] }: Props) {
  if (!resolution || typeof resolution !== 'object') return null;
  const concepts = Array.isArray(resolution.concepts) ? resolution.concepts : [];
  const questions = Array.isArray(resolution.questions) ? resolution.questions : [];
  const prevented = Array.isArray(resolution.state_prevented) ? resolution.state_prevented : [];
  const residualReasons = Array.isArray(resolution.residual_reasons) ? resolution.residual_reasons : [];
  const selected = Array.isArray(evidence?.selected) ? evidence.selected : [];
  const conceptLeg = evidence?.legs?.concept_resolution || {};
  const conceptData = conceptLeg?.data && typeof conceptLeg.data === 'object' ? conceptLeg.data : {};
  const coverage = conceptData.status || conceptLeg.health || conceptLeg.error || 'not recorded';
  const sources = Array.isArray(conceptData.items) ? conceptData.items : [];
  const sourceStatus = conceptData.source_status && typeof conceptData.source_status === 'object'
    ? conceptData.source_status : {};
  const researchRan = selected.includes('concept_resolution');
  const simulationContract = conceptData.authority === 'simulation_contract_only';
  const commitment = caseObligations.find((item: any) => item?.kind === 'buyer_commitment') || null;
  const alignedSkus = [
    ...(Array.isArray(alignment?.exact) ? alignment.exact : []),
    ...(Array.isArray(alignment?.qualified) ? alignment.qualified : []),
    ...(Array.isArray(alignment?.alternatives) ? alignment.alternatives : []),
  ].filter(Boolean);

  return (
    <section data-testid="semantic-resolution-trace" style={{ border: '1px solid #cbd5e1', borderRadius: 10, padding: 12, marginBottom: 14 }}>
      <div style={{ fontWeight: 750, marginBottom: 8 }}>How this request was understood</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(130px, 0.35fr) 1fr', gap: '6px 12px', fontSize: 13 }}>
        {resolution.desired_outcome && <><span style={{ color: '#64748b' }}>Outcome understood</span><strong>{resolution.desired_outcome}</strong></>}
        <span style={{ color: '#64748b' }}>Decision</span>
        <strong>{label(resolution.outcome)}</strong>
        <span style={{ color: '#64748b' }}>Catalog authority</span>
        <strong>{label(resolution.catalog_authority)}</strong>
        <span style={{ color: '#64748b' }}>Residual route</span>
        <strong data-testid="semantic-residual-route">{label(resolution.residual_route || 'not recorded')}</strong>
        {residualReasons.length > 0 && <>
          <span style={{ color: '#64748b' }}>Why this route</span>
          <span>{residualReasons.map(label).join(' · ')}</span>
        </>}
        <span style={{ color: '#64748b' }}>Concepts</span>
        <span>{concepts.length ? concepts.map((item: any) => `${item.text} (${label(item.status)})`).join(' · ') : 'No material ambiguity proposed'}</span>
        <span style={{ color: '#64748b' }}>Evidence coverage</span>
        <span>{researchRan ? label(coverage) : 'concept lane not required'}</span>
        <span style={{ color: '#64748b' }}>Next permitted action</span>
        <strong>{label(resolution.next_permitted_action)}</strong>
      </div>

      {questions.length > 0 && (
        <div style={{ marginTop: 10, padding: 9, background: '#f8fafc', borderRadius: 8 }}>
          <strong>Questions decomposed</strong>
          {questions.map((item: any, index: number) => (
            <div key={item.question_id || index} style={{ marginTop: 4 }}>
              {index + 1}. {item.question || item.text}{' '}
              <strong style={{ color: '#b45309' }}>MISSING</strong>
            </div>
          ))}
        </div>
      )}

      {researchRan && (
        <div data-testid="semantic-evidence-coverage" style={{ marginTop: 10, padding: 9, background: '#f8fafc', borderRadius: 8 }}>
          <strong>Evidence coverage</strong>
          <div style={{ marginTop: 5 }}>Concept resolution: <strong>{label(coverage)}</strong></div>
          {resolution.catalog_authority === 'blocked' && <>
            <div>Catalog capability: <strong>blocked until requirements are qualified</strong></div>
            <div>Inventory ATP: <strong>withheld until product fit is established</strong></div>
            <div>Supplier capability: <strong>not run before buyer commitment</strong></div>
          </>}
        </div>
      )}

      {(alignment || commitment) && (
        <div data-testid="semantic-commercial-authority" style={{ marginTop: 10, padding: 9, background: '#f0fdf4', borderRadius: 8 }}>
          <strong>Qualified commercial authority chain</strong>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(140px, 0.35fr) 1fr', gap: '5px 10px', marginTop: 7, fontSize: 13 }}>
            <span style={{ color: '#64748b' }}>Catalog alignment</span>
            <strong>{label(alignment?.status || 'not recorded')}</strong>
            <span style={{ color: '#64748b' }}>Evidence-qualified SKUs</span>
            <span>{alignedSkus.length ? alignedSkus.join(' · ') : 'none recorded'}</span>
            {commitment && <>
              <span style={{ color: '#64748b' }}>Selected SKU / quantity</span>
              <span>{commitment.selected_sku || 'not selected'} · {commitment.quantity ?? 'quantity not recorded'}</span>
              <span style={{ color: '#64748b' }}>ATP evidence</span>
              <span>{commitment.atp_snapshot?.source_version || 'version missing'} · {sourceTime(commitment.atp_snapshot?.observed_at)}</span>
              <span style={{ color: '#64748b' }}>Commitment state</span>
              <strong>{label(commitment.status || 'not recorded')}</strong>
              <span style={{ color: '#64748b' }}>Authorization</span>
              <strong>{commitment.authorization_granted ? 'granted' : 'not granted'}</strong>
            </>}
          </div>
        </div>
      )}

      {researchRan && conceptData.query && (
        <details open data-testid="semantic-research-provenance" style={{ marginTop: 10, padding: 9, border: '1px solid #dbeafe', borderRadius: 8 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 700 }}>Exact external research used</summary>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(120px, 0.3fr) 1fr', gap: '5px 10px', marginTop: 8, fontSize: 13 }}>
            <span style={{ color: '#64748b' }}>Outbound query</span><code>{conceptData.query}</code>
            <span style={{ color: '#64748b' }}>Query fingerprint</span><code>{conceptData.query_hash || 'not recorded'}</code>
            <span style={{ color: '#64748b' }}>Provider</span><span>{label(conceptData.provider_id || 'not recorded')}</span>
            <span style={{ color: '#64748b' }}>Run / cache</span><span>{label(conceptData.provider_run_status)} / {label(conceptData.cache_status)}</span>
            <span style={{ color: '#64748b' }}>Result health</span>
            <span>{label(sourceStatus.status || conceptLeg.health)} · {sourceStatus.hit_count ?? sources.length} result(s) · {sourceStatus.latency_ms ?? evidence?.ms ?? '—'} ms</span>
            <span style={{ color: '#64748b' }}>Authority</span><strong>{label(conceptData.authority || 'candidate only')}</strong>
          </div>
          {sources.length > 0 ? (
            <ol style={{ margin: '8px 0 0', paddingLeft: 20 }}>
              {sources.map((item: any, index: number) => (
                <li key={`${item.url || item.source_domain || 'source'}-${index}`} style={{ marginTop: 5 }}>
                  {item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title || item.source_domain || 'Source'}</a> : (item.title || item.source_domain || 'Source')}
                  <span style={{ color: '#64748b' }}> · {item.source_domain || 'domain not recorded'} · {sourceTime(item.fetched_ts)}</span>
                </li>
              ))}
            </ol>
          ) : <div style={{ marginTop: 7, color: '#64748b' }}>No external result was used.</div>}
          <div style={{ marginTop: 7, color: '#92400e' }}>
            {simulationContract
              ? 'Synthetic qualification contract only — this proves the governed workflow, not live vendor requirements or availability.'
              : 'Search results are untrusted candidates until an approved source policy and stable citation verify the claim.'}
          </div>
        </details>
      )}

      {resolution.outcome === 'clarify' && (
        <div style={{ marginTop: 10 }}><strong>State changed:</strong> clarification requested</div>
      )}
      {prevented.length > 0 && (
        <div style={{ marginTop: 10, padding: 9, background: '#fff7ed', color: '#9a3412', borderRadius: 8 }}>
          <strong>State prevented:</strong> {prevented.map(label).join(' · ')}
        </div>
      )}
    </section>
  );
}
