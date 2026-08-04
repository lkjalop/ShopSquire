import React from 'react';

type Coverage = { check?: string; status?: string; authority_effect?: string };

const label = (value: unknown, fallback = 'Not recorded') => String(value ?? '').trim() || fallback;
const safeSnippet = (value: unknown) => {
  const text = label(value, '');
  if (!text) return '';
  return text
    .replace(/ignore\s+(?:all\s+)?previous/ig, '[instruction marker]')
    .replace(/system\s*:/ig, '[role marker] ')
    .replace(/approve(?:d)?\s*=\s*true/ig, '[approval forgery]')
    .slice(0, 180);
};

export function ArtifactIdentity({ item }: { item: any }) {
  const artifact = item?.artifact || {};
  return <section aria-label="Artifact identity">
    <h4>Artifact identity</h4>
    <div>File: {label(item?._filename || item?.filename, 'Unnamed attachment')}</div>
    <div>SHA-256: {label(artifact?.sha256, 'Not persisted')}</div>
    <div>Verdict version: {label(artifact?.verdict_version)}</div>
    <div>State: {label(artifact?.state || item?.security?.artifact_state)}</div>
  </section>;
}

export function InspectionCoverage({ rows }: { rows: Coverage[] }) {
  const values = Array.isArray(rows) ? rows : [];
  return <section aria-label="Inspection coverage">
    <h4>Inspection coverage</h4>
    {values.length === 0 ? <div>Coverage was not recorded for this artifact.</div> : (
      <table><thead><tr><th>Check</th><th>Status</th><th>Authority effect</th></tr></thead>
        <tbody>{values.map((row, idx) => <tr key={`${row.check}-${idx}`}>
          <td>{label(row.check)}</td><td>{label(row.status)}</td><td>{label(row.authority_effect, 'none')}</td>
        </tr>)}</tbody></table>
    )}
  </section>;
}

export function ContainmentLedger({ containment }: { containment: any }) {
  const rows = Object.entries(containment || {});
  return <section aria-label="Containment ledger"><h4>Containment ledger</h4>
    {rows.length ? rows.map(([key, value]) => <div key={key}>{key.replace(/_/g, ' ')}: {label(value)}</div>) : <div>No containment actions recorded.</div>}
  </section>;
}

export function ExtractedContentProvenance({ item }: { item: any }) {
  const security = item?.security || {};
  const provenance = security?.evidence?.artifact_provenance || security?.payload_analysis?.artifact_provenance || [];
  const extracted = safeSnippet(security?.extracted_text || item?.extracted_text);
  return <section aria-label="Extracted content provenance"><h4>Extracted content provenance</h4>
    {extracted ? <details><summary>Show defanged extracted-content sample</summary><code>{extracted}</code></details> : <div>No extracted text recorded.</div>}
    {Array.isArray(provenance) && provenance.length ? provenance.map((row: any, idx: number) =>
      <div key={idx}>{label(row?.source_file)} {' · '} {label(row?.extraction_method)} {' · '} {label(row?.match_ref)}</div>
    ) : <div>No string-level provenance recorded.</div>}
  </section>;
}

export function MonitoringDelivery({ security }: { security: any }) {
  const handoff = security?.siem_handoff || security?.monitoring_delivery || {};
  const event = handoff?.event || {};
  const status = handoff?.status || handoff;
  const details = Array.isArray(status?.details) ? status.details : [];
  const configured = details.length > 0 || [...(status?.queued || []), ...(status?.sent || []), ...(status?.failed || []), ...(status?.dlq || [])].length > 0;
  return <section aria-label="Monitoring delivery">
    <h4>Monitoring delivery</h4>
    <div>Event schema: {label(event?.schema_version, 'Not emitted')}</div>
    <div>Correlation: {label(event?.trace_id || event?.decision_id, 'Not recorded')}</div>
    {!configured ? <div>No monitoring destination configured or no handoff attempted.</div> : details.map((row: any, idx: number) =>
      <div key={`${row?.target}-${idx}`}>
        {label(row?.target)}: {label(row?.status)} {' · '} attempts {label(row?.attempts, '0')}
        {row?.http_status ? ` · HTTP ${row.http_status}` : ''}
      </div>
    )}
    {status?.worker_submission === 'accepted' ? <div role="status">Durable worker accepted the delivery job.</div> : null}
    {status?.worker_submission === 'failed' ? <div role="alert">Monitoring delivery was not accepted by the worker. Security operations must review the outbox.</div> : null}
    {Array.isArray(status?.sent) && status.sent.length > 0 ? <div>Transport accepted; analyst acknowledgement is not yet recorded.</div> : null}
    {Array.isArray(status?.dlq) && status.dlq.length > 0 ? <div role="alert">Delivery requires operator attention: {status.dlq.join(', ')} is in the dead-letter queue.</div> : null}
  </section>;
}

export function BatchIsolation({ items }: { items: any[] }) {
  if (!Array.isArray(items) || items.length < 2) return null;
  return <section aria-label="Batch isolation"><h4>Batch isolation</h4>
    {items.map((item, idx) => <div key={idx}>
      {label(item?._filename || item?.filename, `Attachment ${idx + 1}`)}: {label(item?.artifact?.state || item?.security?.artifact_state)}
    </div>)}
    <div>Each file retains its own verdict. Combined commercial authority requires every bound artifact to be clean.</div>
  </section>;
}

export function FrameworkHypotheses({ security }: { security: any }) {
  const observed = security?.payload_analysis?.claim_status === 'observed';
  return <section aria-label="Framework hypotheses"><h4>Framework hypotheses</h4>
    <div>Claim status: {observed ? 'observed artifact behavior' : label(security?.claim_status, 'hypothesis')}</div>
    <div>Mapping version: {label(security?.mapping_version, 'Not recorded')}</div>
    <div>Runtime compromise: {security?.runtime_confirmation_required ? 'not confirmed; runtime evidence required' : 'not claimed'}</div>
  </section>;
}

export default function ArtifactSecuritySummary({ item, batchItems, monitoringDelivery }: { item: any; batchItems: any[]; monitoringDelivery?: any }) {
  const security = item?.security || {};
  return <div data-testid="artifact-security-summary">
    <ArtifactIdentity item={item} />
    <InspectionCoverage rows={security?.inspection_coverage || []} />
    <ContainmentLedger containment={security?.containment || {}} />
    <ExtractedContentProvenance item={item} />
    <BatchIsolation items={batchItems} />
    <FrameworkHypotheses security={security} />
    <MonitoringDelivery security={monitoringDelivery ? { ...security, siem_handoff: monitoringDelivery } : security} />
  </div>;
}
