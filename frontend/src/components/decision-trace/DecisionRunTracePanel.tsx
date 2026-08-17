export default function DecisionRunTracePanel({ data, status, classNames }: {
  data: any;
  status: 'idle' | 'loading' | 'ready' | 'unavailable';
  classNames: Record<string, string>;
}) {
  if (status === 'idle') return null;
  if (status === 'loading') return <div className={classNames.empty}>Loading revisioned decision evidence...</div>;
  if (status === 'unavailable' || !data?.latest) {
    return <div className={classNames.empty}>No revisioned decision run is available. No historical state is inferred.</div>;
  }
  const run = data.latest;
  return (
    <section className={classNames.summaryPane} data-testid="decision-run-trace">
      <h3>Decision snapshot and temporal replay</h3>
      <p>
        Revision {run.case_revision} evaluated using evidence known at{' '}
        <time dateTime={run.knowledge_cutoff}>{run.knowledge_cutoff}</time>.
      </p>
      <p>Evaluation time: <time dateTime={run.evaluation_time}>{run.evaluation_time}</time></p>
      <p>Commerce authority: none - this trace cannot mutate cart, RFQ, payment or shipment.</p>
      <h4>Stage receipts</h4>
      <ul>
        {(run.stage_receipts || []).map((receipt: any) => (
          <li key={receipt.stage_id || receipt.stage}>
            {receipt.stage}: {receipt.status}
            {receipt.reason_code ? ` (${receipt.reason_code})` : ''}
          </li>
        ))}
      </ul>
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
