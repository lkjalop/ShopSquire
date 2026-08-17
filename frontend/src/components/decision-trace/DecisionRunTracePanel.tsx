import { useState } from 'react';


export default function DecisionRunTracePanel({ data, status, classNames }: {
  data: any;
  status: 'idle' | 'loading' | 'ready' | 'unavailable';
  classNames: Record<string, string>;
}) {
  const [view, setView] = useState<'changed' | 'known' | 'fulfil'>('changed');
  if (status === 'idle') return null;
  if (status === 'loading') return <div className={classNames.empty}>Loading revisioned decision evidence...</div>;
  if (status === 'unavailable' || !data?.latest) {
    return <div className={classNames.empty}>No revisioned decision run is available. No historical state is inferred.</div>;
  }
  const run = data.latest;
  const views = data.views || {};
  const selectedView = view === 'changed'
    ? views.what_changed : view === 'known'
      ? views.what_was_known_then : views.who_can_fulfil_now;
  return (
    <section className={classNames.summaryPane} data-testid="decision-run-trace">
      <h3>Decision snapshot and temporal replay</h3>
      <p>
        Revision {run.case_revision} evaluated using evidence known at{' '}
        <time dateTime={run.knowledge_cutoff}>{run.knowledge_cutoff}</time>.
      </p>
      <p>Evaluation time: <time dateTime={run.evaluation_time}>{run.evaluation_time}</time></p>
      <p>Commerce authority: none - this trace cannot mutate cart, RFQ, payment or shipment.</p>
      <h4>Ask the decision record</h4>
      <div role="group" aria-label="Decision record views">
        <button type="button" aria-pressed={view === 'changed'} onClick={() => setView('changed')}>What changed?</button>{' '}
        <button type="button" aria-pressed={view === 'known'} onClick={() => setView('known')}>What was known then?</button>{' '}
        <button type="button" aria-pressed={view === 'fulfil'} onClick={() => setView('fulfil')}>Who can fulfil now?</button>
      </div>
      {selectedView && (
        <div data-testid="decision-record-view">
          {view === 'changed' && (
            <p>
              Revision {selectedView.from_revision ?? 'initial'} → {selectedView.to_revision}.{' '}
              {selectedView.invalidation_count || 0} invalidation(s) recorded.
            </p>
          )}
          {view === 'known' && (
            <p>
              Evidence cutoff {selectedView.knowledge_cutoff}. Future evidence is excluded from this replay.
            </p>
          )}
          {view === 'fulfil' && (
            <>
              <p>{selectedView.evidence_warning}</p>
              <ul>{(selectedView.supplier_candidates || []).map((candidate: any, index: number) => (
                <li key={`${candidate.supplier_reference}:${candidate.offered_sku}:${index}`}>
                  {candidate.supplier_reference}: {candidate.quantity_available ?? 'undisclosed'} × {candidate.offered_sku || 'configuration undisclosed'}; {candidate.response_status}
                </li>
              ))}</ul>
            </>
          )}
        </div>
      )}
      <h4>Stage receipts</h4>
      <ul>
        {(run.stage_receipts || []).map((receipt: any) => (
          <li key={receipt.stage_id || receipt.stage}>
            {receipt.stage}: {receipt.status}
            {receipt.reason_code ? ` (${receipt.reason_code})` : ''}
            {(receipt.tool_selection_receipts || []).map((tool: any, index: number) => (
              <div key={`${receipt.stage}:tool:${index}`}>
                ToolScope {String(tool.capability || 'capability not recorded')}: {String(tool.outcome || 'not recorded')}
                {Array.isArray(tool.selected_deployment_ids) && tool.selected_deployment_ids.length > 0
                  ? ` via ${tool.selected_deployment_ids.join(', ')}` : ''}
              </div>
            ))}
          </li>
        ))}
      </ul>
      {(run.evidence_watermarks || []).length > 0 && (
        <>
          <h4>Evidence watermarks</h4>
          <ul>{run.evidence_watermarks.map((row: any) => (
            <li key={`${row.source}:${row.source_version || ''}`}>
              {row.source}: {row.state}; observed <time dateTime={row.observed_at}>{row.observed_at}</time>
            </li>
          ))}</ul>
        </>
      )}
      {(run.temporal_conflicts || []).length > 0 && (
        <>
          <h4>Unresolved temporal conflicts</h4>
          <ul>
            {run.temporal_conflicts.map((conflict: any) => (
              <li key={conflict.conflict_id}>
                {conflict.subject} / {conflict.attribute}: {conflict.status}; resolution owner {conflict.resolution_owner}
              </li>
            ))}
          </ul>
        </>
      )}
      {(run.invalidations || []).length > 0 && (
        <>
          <h4>What changed</h4>
          <ul>{run.invalidations.map((row: any) => <li key={`${row.code}:${row.changed_path}`}>{row.changed_path} invalidated {row.invalidated_stages.join(', ')}</li>)}</ul>
        </>
      )}
      <details>
        <summary>Dependency evidence ({(data.dependency_edges || []).length} edges)</summary>
        <ul>{(data.dependency_edges || []).map((edge: any) => <li key={edge.edge_id}>{edge.source_ref} -&gt; {edge.target_ref} ({edge.relation})</li>)}</ul>
      </details>
    </section>
  );
}
