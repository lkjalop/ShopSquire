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
  research_plan_id?: string | null;
  ambiguity_objects?: { ambiguity_id: string }[];
  research_obligations?: {
    obligation_id: string;
    resolution_owner: 'catalog' | 'research' | 'buyer' | 'computation' | 'supplier' | 'tenant_policy' | 'human';
    status: string;
  }[];
  source_candidate_ids?: string[];
};

type Props = {
  exploration: AmbiguityExploration;
  onResearch: () => void;
  onUpload: () => void;
  onEnterSpecifications: () => void;
};

export default function AmbiguityExplorationPanel({
  exploration, onResearch, onUpload, onEnterSpecifications,
}: Props) {
  const question = exploration.next_question?.text || exploration.next_question?.question;
  return (
    <section data-testid="ambiguity-exploration" style={{ margin: 12, padding: 12, border: '1px solid #93c5fd', borderRadius: 10 }}>
      <strong>Purpose</strong>
      <div>{exploration.retained_purpose}</div>
      <div style={{ marginTop: 7, fontSize: 12 }}>
        Status: {exploration.status === 'researched'
          ? 'Researched — scoped product requirements compiled; remaining gaps stay conditional'
          : exploration.status === 'context_only'
            ? 'Context researched — no authoritative product requirements were established'
            : exploration.status === 'unresolved'
              ? 'Research completed — no accepted scoped claims were found'
              : 'Provisional — external research not yet authorized'}
      </div>
      {exploration.interpretations?.length > 0 && (
        <div style={{ marginTop: 9 }}>
          <strong>Current interpretations</strong>
          <ul>{exploration.interpretations.map((item, index) => (
            <li key={item.hypothesis_id || index}>{item.label || item.hypothesis_id || `Interpretation ${index + 1}`}</li>
          ))}</ul>
        </div>
      )}
      {question && <div data-testid="high-information-question" style={{ marginTop: 8 }}><strong>One question:</strong> {question}</div>}
      {exploration.research_obligations?.length ? (
        <div data-testid="research-resolution-owners" style={{ marginTop: 8, fontSize: 12 }}>
          {exploration.research_obligations.map((item) => (
            <div key={item.obligation_id}>{item.obligation_id}: {item.resolution_owner} ({item.status})</div>
          ))}
        </div>
      ) : null}
      <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 10 }}>
        {exploration.status === 'provisional' && (
          <button type="button" onClick={onResearch} style={{ background: '#f15a0a', color: '#fff', border: 0, borderRadius: 6, padding: '7px 11px', fontWeight: 700 }}>Research approved sources</button>
        )}
        <button type="button" onClick={onUpload} style={{ background: '#fff', color: '#173b64', border: '1px solid #173b64', borderRadius: 6, padding: '7px 11px' }}>Upload requirements</button>
        <button type="button" onClick={onEnterSpecifications} style={{ background: '#fff', color: '#173b64', border: '1px solid #173b64', borderRadius: 6, padding: '7px 11px' }}>Enter specifications</button>
        <span style={{ fontSize: 12, alignSelf: 'center' }}>Continue provisionally below</span>
      </div>
      <div data-testid="ambiguity-accounting" style={{ marginTop: 8, fontSize: 11 }}>
        Execution: {exploration.execution} · Evidence: {exploration.evidence} · Decision: {exploration.decision}
        {' · '}External calls: {exploration.provider_accounting.external_calls}
        {' · '}Paid calls: {exploration.provider_accounting.paid_calls}
        {' · '}Cart authority: {exploration.cart_authority}
      </div>
    </section>
  );
}
