type Props = {
  insights: any[];
  classNames: Record<string, string>;
};

export default function HippographEvidencePanel({ insights, classNames }: Props) {
  if (!Array.isArray(insights) || insights.length === 0) return null;
  return (
    <section data-testid="hippograph-evidence-surface" aria-label="Hippograph provenance paths" className={classNames.anchorBlock}>
      <div className={classNames.sectionTitle}>Hippograph Evidence Paths</div>
      <div className={classNames.muted}>
        Evidence-only retrieval. It can explain or prioritize review, but cannot authorize a commercial action.
      </div>
      {insights.map((insight: any, index: number) => {
        const path = insight?.evidence_path || {};
        const health = insight?.source_health || {};
        return (
          <details key={`${insight?.id || 'insight'}-${index}`} style={{ marginTop: 8 }} open={index === 0}>
            <summary style={{ cursor: 'pointer', fontWeight: 700 }}>
              {insight?.label || insight?.id || 'Related evidence'} · score {insight?.score ?? 'not recorded'}
              {' · '}{health?.status || 'unknown source health'}
            </summary>
            <div className={classNames.kvRow}><span>Authority</span><span>{insight?.authority || path?.authority || 'evidence_only'}</span></div>
            <div className={classNames.kvRow}><span>Path</span><span>{Array.isArray(path?.nodes) && path.nodes.length ? path.nodes.join(' → ') : 'No bounded path available'}</span></div>
            <div className={classNames.kvRow}><span>Hops</span><span>{path?.hops ?? 'not recorded'}</span></div>
            {Array.isArray(health?.degraded_sources) && health.degraded_sources.length > 0 && (
              <div data-testid="hippograph-degraded-sources" style={{ color: '#b45309', marginTop: 6 }}>
                Degraded sources: {health.degraded_sources.map((source: any) => (
                  `${source?.source || 'unknown'} (${source?.reason || source?.health || 'degraded'})`
                )).join(', ')}
              </div>
            )}
            {(path?.edges || []).map((edge: any, edgeIndex: number) => (
              <div key={`${edge?.source || 'edge'}-${edgeIndex}`} style={{ borderTop: '1px solid #e5e7eb', marginTop: 8, paddingTop: 8 }}>
                <div className={classNames.kvRow}><span>Edge</span><span>{edge?.source} → {edge?.target}</span></div>
                {(edge?.evidence || []).map((item: any, evidenceIndex: number) => (
                  <div key={`${item?.evidence_id || evidenceIndex}`} className={classNames.muted}>
                    evidence {item?.evidence_id || 'unidentified'} · edge {item?.edge_id || 'unidentified'}
                    {' · '}observed {item?.observed_at || 'unknown'}
                    {' · '}effective {item?.effective_at || 'unknown'}
                    {' · '}authority {item?.source_authority || 'unknown'}
                    {' · '}health {item?.source_health || 'unknown'}
                    {' · '}freshness {item?.freshness_weight ?? 'not recorded'}
                  </div>
                ))}
              </div>
            ))}
          </details>
        );
      })}
    </section>
  );
}
