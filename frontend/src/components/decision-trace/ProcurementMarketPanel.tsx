export default function ProcurementMarketPanel({ projection }: { projection: any }) {
  if (!projection) return null;
  const count = projection.scoped_signal_count ?? projection.signal_count;
  const mode = String(projection.mode);
  return <div data-testid="proc-market-intel" style={{ border: '1px solid #6366f1', background: '#eef2ff', borderRadius: 10, padding: '10px 12px', fontSize: 13, marginBottom: 12 }}>
    <div style={{ fontWeight: 700, color: '#3730a3', marginBottom: 4 }}>Market Intelligence — {mode === 'live' ? `${count} scoped signal${Number(count) === 1 ? '' : 's'}` : mode === 'context_only' ? `${projection.signal_count} global context signals (not line-authorizing)` : 'internal-only (no external signal)'}</div>
    <div style={{ marginBottom: 6 }}><strong>{String(projection.action_basis) === 'inventory_only' ? 'Inventory action:' : 'Recommended action:'}</strong> {String(projection.recommendation || '—')}<div style={{ color: '#4b5563', marginTop: 2 }}>{String(projection.rationale || '')}</div></div>
    {Array.isArray(projection.signals) && projection.signals.map((signal: any, index: number) => <div key={signal.id || index} style={{ paddingLeft: 6, borderLeft: `3px solid ${String(signal.severity) === 'critical' ? '#dc2626' : '#f59e0b'}`, marginBottom: 3, color: '#374151' }}><span style={{ fontSize: 9, fontWeight: 700, marginRight: 5 }}>{String(signal.scope || 'context').toUpperCase()}</span>{String(signal.type || '')}{signal.summary ? ` — ${signal.summary}` : ''}</div>)}
    <div style={{ marginTop: 6, fontSize: 11, color: '#6b7280' }}>Deterministic finding-to-action synthesis · advisory only · human-gated supplier send.</div>
  </div>;
}
