import { useHippographView, type HippographViewPurpose } from '../../hooks/useHippographView';

const OPTIONS: Array<{ purpose: HippographViewPurpose; label: string }> = [
  { purpose: 'what_changed', label: 'What changed?' },
  { purpose: 'historical_knowledge', label: 'What was known then?' },
  { purpose: 'supplier_fulfilment', label: 'Who can fulfil this?' },
];

export default function HippographViewSelector({
  active, caseId, apiKey,
}: {
  active: boolean;
  caseId: string;
  apiKey: string;
}) {
  const seedId = `shopping_case:${caseId}`;
  const { purpose, view, status, load } = useHippographView({
    active, seedId, caseId, apiKey,
  });
  if (!apiKey || !caseId) return null;
  const receipt = view?.receipt || {};
  return (
    <section data-testid="hippograph-view-selector" style={{ border: '1px solid #cbd5e1', borderRadius: 8, padding: 10, marginBottom: 10 }}>
      <strong>Hippograph evidence view</strong>
      <div style={{ color: '#64748b', marginTop: 3 }}>
        Bounded, tenant-scoped evidence recall. It cannot rank products or authorize commerce.
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
        {OPTIONS.map((option) => (
          <button
            key={option.purpose}
            type="button"
            aria-pressed={purpose === option.purpose && status !== 'idle'}
            onClick={() => void load(option.purpose)}
            style={{ border: '1px solid #ea580c', background: '#fff', color: '#c2410c', borderRadius: 6, padding: '5px 8px' }}
          >
            {option.label}
          </button>
        ))}
      </div>
      {status === 'loading' && <div role="status" style={{ marginTop: 7 }}>Loading bounded graph view…</div>}
      {status === 'unavailable' && <div role="alert" style={{ marginTop: 7, color: '#b45309' }}>Graph view unavailable; no evidence conclusion was inferred.</div>}
      {status === 'available' && (
        <div data-testid="hippograph-view-receipt" style={{ marginTop: 8 }}>
          <div>Selected edges: <strong>{receipt.selected_edge_ids?.length ?? 0}</strong></div>
          <div>Visited nodes: <strong>{receipt.visited_node_ids?.length ?? 0}</strong></div>
          <div>Known later, excluded: <strong>{receipt.not_yet_known_edge_ids?.length ?? 0}</strong></div>
          <div>Known future, not yet effective: <strong>{receipt.known_future_edge_ids?.length ?? 0}</strong></div>
          <div>Authority: <strong>{receipt.authority || 'evidence_recall_only'}</strong></div>
        </div>
      )}
    </section>
  );
}
