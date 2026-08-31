export type ResearchOutcome = {
  schema_version: 'research-outcome-v1';
  case_id: string;
  case_revision: number;
  operation_id?: string | null;
  identity?: { title?: string | null; publisher?: string | null; app_id?: string | null } | null;
  discovery_status: string;
  source_ownership_status: string;
  fetch_status: string;
  parsed_claim_count: number;
  held_claim_count: number;
  accepted_claim_count: number;
  rejected_claim_count: number;
  requirement_completeness: string;
  catalog_authority: string;
  commerce_authority: string;
  next_action?: string | null;
  failure_code?: string | null;
};

const words = (value: unknown) => String(value || 'not recorded').replaceAll('_', ' ');

export default function ResearchOutcomeSummary({ outcome }: { outcome: ResearchOutcome }) {
  const held = Number(outcome.held_claim_count || 0) > 0;
  const accepted = Number(outcome.accepted_claim_count || 0) > 0;
  const state = held && Number(outcome.rejected_claim_count || 0) > 0 && !accepted
    ? 'Held source evidence · rejected for case'
    : held ? 'Held for review'
    : outcome.source_ownership_status === 'verified' ? 'Verified evidence'
      : outcome.source_ownership_status === 'accepted_case_only' ? 'Accepted case-only evidence'
        : Number(outcome.rejected_claim_count || 0) > 0 && !accepted ? 'Rejected evidence'
        : accepted ? 'Provisional constraints'
          : outcome.source_ownership_status === 'discovered_candidate'
            ? 'Publisher discovered' : 'Research unresolved';
  return (
    <section
      data-testid="research-outcome-summary"
      style={{
        margin: '0 0 10px', padding: 10, borderRadius: 8,
        border: `1px solid ${held ? '#f59e0b' : accepted ? '#10b981' : '#94a3b8'}`,
        background: held ? '#fffbeb' : accepted ? '#ecfdf5' : '#f8fafc',
      }}
    >
      <strong>{state}</strong>
      {outcome.identity?.title ? <> · {outcome.identity.title}</> : null}
      <div style={{ marginTop: 4, fontSize: 12 }}>
        Discovery: <strong>{words(outcome.discovery_status)}</strong>
        {' · '}Fetch: <strong>{words(outcome.fetch_status)}</strong>
        {' · '}Requirements: <strong>{words(outcome.requirement_completeness)}</strong>
      </div>
      <div style={{ marginTop: 2, fontSize: 12 }}>
        Parsed: <strong>{outcome.parsed_claim_count}</strong>
        {' · '}Held: <strong>{outcome.held_claim_count}</strong>
        {' · '}Accepted: <strong>{outcome.accepted_claim_count}</strong>
        {' · '}Rejected: <strong>{outcome.rejected_claim_count}</strong>
      </div>
      <div style={{ marginTop: 2, fontSize: 12 }}>
        Catalog authority: <strong>{words(outcome.catalog_authority)}</strong>
        {' · '}Commerce authority: <strong>{words(outcome.commerce_authority)}</strong>
      </div>
      {outcome.next_action ? (
        <div style={{ marginTop: 4, fontSize: 12 }}>
          Next: <strong>{words(outcome.next_action)}</strong>
          {outcome.failure_code ? <> · {words(outcome.failure_code)}</> : null}
        </div>
      ) : null}
    </section>
  );
}
