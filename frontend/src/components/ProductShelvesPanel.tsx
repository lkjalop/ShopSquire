import React from 'react';

export type ShelfProduct = {
  identity_key: string;
  title: string;
  price_cents: number;
  currency: string;
  fit_status: 'qualified' | 'conditional' | 'failed';
  relevance_score: number;
  product: { sku: string; identifier?: string; form_factor?: string };
  meets?: string[];
  conditional?: string[];
  unknowns?: string[];
  misses?: string[];
  compromises?: string[];
  why_ranked?: string;
  explanation?: {
    summary: string;
    evidence_basis: 'verified_exact' | 'conditional' | 'provisional';
    budget_note?: string | null;
    availability_note?: string | null;
    claim_refs?: string[];
  } | null;
  freshness_status?: string;
  evidence_freshness?: {
    specification: string; specification_observed_at?: string | null;
    price: string; price_observed_at?: string | null;
    availability: string; availability_observed_at?: string | null;
  };
  availability?: {
    location_id: string; status: string; quantity?: number | null;
    lead_time_min_days?: number | null; lead_time_max_days?: number | null;
    freshness_status?: string;
  }[];
  commercial_decision?: {
    status: string;
    fit_tier: string;
    quantity_outcome: string;
    budget_outcome: string;
    resolution_owner: string;
    reasons?: string[];
  };
};

type ProductShelf = {
  shelf_id: string;
  scope_label: string;
  budget_band: 'best' | 'within_budget' | 'stretch';
  initial: ShelfProduct[];
  next_page: ShelfProduct[];
  remaining_count: number;
};

export type ProductShelfProjection = {
  schema_version: 'product-shelves-v1';
  shelves: ProductShelf[];
  evidence_status?: 'provisional' | 'researched' | 'context_only' | 'unresolved';
  official_claim_count?: number;
  context_claim_count?: number;
  research_delta?: {
    sku: string; before?: number | null; after?: number | null;
    movement: number; reason: string;
  }[];
  research_receipt?: {
    summary: string;
    publisher_labels: string[];
    requirements_established: number;
    context_claims: number;
    unresolved_count: number;
    product_identity_status: 'separately_verified';
    availability_status: 'separately_verified';
  };
  narration_projection?: {
    purpose: string;
    accepted_requirements: Record<string, unknown>[];
    shelf_summary: string;
    top_product_sentences: {
      sku: string; sentence: string; evidence_basis: 'verified' | 'conditional' | 'failed';
    }[];
    reranking_summary: string;
  };
};

const money = (value: number, currency: string) => new Intl.NumberFormat('en-AU', {
  style: 'currency', currency: currency || 'AUD', maximumFractionDigits: 0,
}).format(value / 100);

const secondaryCommerceStyle = {
  background: '#fff', color: '#c2410c', border: '1px solid #f15a0a',
  borderRadius: 6, padding: '6px 9px', fontWeight: 700,
} as const;

export default function ProductShelvesPanel({ projection, onPropose }: {
  projection: ProductShelfProjection;
  onPropose?: (product: ShelfProduct, quantity: number) => void;
}) {
  if (!projection?.shelves?.length) return null;
  return (
    <section data-testid="product-shelves" aria-label="Provisional product shelves" style={{ padding: 12 }}>
      {projection.research_receipt ? (
        <section data-testid="buyer-research-receipt" style={{ border: '1px solid #86efac', background: '#f0fdf4', borderRadius: 8, padding: 9, marginBottom: 10, fontSize: 12 }}>
          <strong>Research receipt</strong>
          <div>{projection.research_receipt.summary}</div>
          <details style={{ marginTop: 4 }}>
            <summary>What remains separately verified</summary>
            Product identity and availability are checked against their own evidence and freshness clocks.
          </details>
        </section>
      ) : null}
      {projection.narration_projection ? (
        <div data-testid="deterministic-shelf-narration" style={{ fontSize: 12, marginBottom: 10, color: '#334155' }}>
          {projection.narration_projection.shelf_summary}
        </div>
      ) : null}
      <div style={{ fontSize: 12, marginBottom: 10, color: projection.evidence_status === 'researched' ? '#065f46' : '#92400e' }}>
        {projection.evidence_status === 'researched'
          ? `Official research compiled ${projection.official_claim_count || 0} scoped product claims and ${projection.context_claim_count || 0} context claims.`
          : projection.evidence_status === 'context_only'
            ? `Official research found ${projection.context_claim_count || 0} context claims but no authoritative product requirements. These shelves remain provisional.`
            : projection.evidence_status === 'unresolved'
              ? 'Approved-source research completed without accepted scoped claims. These shelves remain provisional.'
              : 'Provisional exploration — accepted buyer constraints are not independently verified.'}
      </div>
      {['researched', 'context_only', 'unresolved'].includes(String(projection.evidence_status)) && (
        <section data-testid="research-reranking-delta" style={{ border: `1px solid ${projection.evidence_status === 'researched' ? '#86efac' : '#fbbf24'}`, background: projection.evidence_status === 'researched' ? '#f0fdf4' : '#fffbeb', borderRadius: 8, padding: 9, marginBottom: 12 }}>
          <strong>{projection.evidence_status === 'researched'
            ? 'What changed after approved-source research'
            : 'Why the shortlist remains provisional'}</strong>
          {projection.research_delta?.length ? projection.research_delta.map((row) => (
            <div key={row.sku} style={{ fontSize: 12, marginTop: 4 }}>
              {row.sku}: {row.before ?? 'not ranked'} → {row.after ?? 'not ranked'} — {row.reason}
            </div>
          )) : (
            <div style={{ fontSize: 12, marginTop: 4 }}>
              {projection.narration_projection?.reranking_summary || (
                projection.evidence_status === 'researched'
                  ? 'Ranking order did not change; evidence status and visible gaps were updated.'
                  : 'No product requirements were established, so research did not authorize a verified rerank.'
              )}
            </div>
          )}
        </section>
      )}
      {projection.shelves.map((shelf) => (
        <Shelf
          key={shelf.shelf_id}
          shelf={shelf}
          onPropose={onPropose}
          narration={projection.narration_projection?.top_product_sentences || []}
        />
      ))}
    </section>
  );
}

function Shelf({ shelf, onPropose, narration }: {
  shelf: ProductShelf;
  onPropose?: (product: ShelfProduct, quantity: number) => void;
  narration: { sku: string; sentence: string }[];
}) {
  const [expanded, setExpanded] = React.useState(false);
  const [quantities, setQuantities] = React.useState<Record<string, number>>({});
  const products = expanded ? [...shelf.initial, ...shelf.next_page] : shelf.initial;
  const band = shelf.budget_band === 'within_budget' ? 'Within budget'
    : shelf.budget_band === 'stretch' ? 'Stretch' : 'Best fit';
  return (
    <section data-testid={`product-shelf-${shelf.shelf_id}`} style={{ marginBottom: 16 }}>
      <h3 style={{ margin: '0 0 3px', fontSize: 15 }}>{shelf.scope_label}</h3>
      <div style={{ fontSize: 12, marginBottom: 7 }}>{band}</div>
      <div data-testid={`shelf-summary-${shelf.shelf_id}`} style={{ fontSize: 12, marginBottom: 7, color: '#475569' }}>
        {shelf.initial.length} leading option{shelf.initial.length === 1 ? '' : 's'} ranked for this scope;{' '}
        {shelf.initial.filter((item) => item.fit_status === 'qualified').length
          ? `${shelf.initial.filter((item) => item.fit_status === 'qualified').length} have verified exact-configuration fit.`
          : 'all remain conditional where exact evidence or accepted requirements are incomplete.'}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 7 }}>
        {products.map((item) => (
          <article key={item.identity_key} style={{ border: '1px solid #cbd5e1', borderRadius: 8, padding: 8 }}>
            <strong style={{ fontSize: 12 }}>{item.title}</strong>
            <div style={{ marginTop: 6 }}>{money(item.price_cents, item.currency)}</div>
            <div style={{ marginTop: 4, fontSize: 11, fontWeight: 700, color: item.fit_status === 'qualified' ? '#047857' : '#92400e' }}>
              {item.fit_status === 'qualified' ? 'Verified fit' : 'Conditional fit'}
            </div>
            <div style={{ marginTop: 5, fontSize: 11 }}>{item.why_ranked || 'Provisional catalog exploration.'}</div>
            {narration.find((row) => row.sku === item.product.sku)?.sentence ? (
              <div data-testid={`product-narration-${item.product.sku}`} style={{ marginTop: 5, fontSize: 11, color: '#334155' }}>
                {narration.find((row) => row.sku === item.product.sku)?.sentence}
              </div>
            ) : null}
            {item.explanation?.budget_note ? <div style={{ fontSize: 11 }}>{item.explanation.budget_note}</div> : null}
            {item.explanation?.availability_note ? <div style={{ fontSize: 11 }}>{item.explanation.availability_note}</div> : null}
            {freshAvailableQuantity(item) != null ? (
              <div style={{ fontSize: 11 }}>Verified portfolio-network stock: {freshAvailableQuantity(item)}</div>
            ) : null}
            <details style={{ marginTop: 6, fontSize: 11 }}>
              <summary>Why this recommendation</summary>
              <div>Exact configuration: {item.product.identifier || 'not verified'}</div>
            {item.commercial_decision ? (
              <div>
                Commercial status: {item.commercial_decision.status}
                {' · '}quantity {item.commercial_decision.quantity_outcome}
                {' · '}budget {item.commercial_decision.budget_outcome}
                {' · '}owner {item.commercial_decision.resolution_owner}
              </div>
            ) : null}
            {item.meets?.length ? <div style={{ fontSize: 11 }}>Meets: {item.meets.join(', ')}</div> : null}
            {item.conditional?.length ? <div style={{ fontSize: 11 }}>Conditional: {item.conditional.join(', ')}</div> : null}
            {item.unknowns?.length ? <div style={{ fontSize: 11 }}>Unknown: {item.unknowns.join(', ')}</div> : null}
            {item.misses?.length ? <div style={{ fontSize: 11, color: '#991b1b' }}>Minimum misses: {item.misses.join(', ')}</div> : null}
            {item.compromises?.length ? <div style={{ fontSize: 11, color: '#92400e' }}>Recommendation compromises: {item.compromises.join(', ')}</div> : null}
            {item.evidence_freshness ? (
              <div style={{ fontSize: 11 }}>
                Freshness: specification {item.evidence_freshness.specification}
                {' · '}price {item.evidence_freshness.price}
                {' · '}availability {item.evidence_freshness.availability}
              </div>
            ) : <div style={{ fontSize: 11 }}>Evidence freshness: {item.freshness_status || 'unknown'}</div>}
            {item.availability?.length ? (
              <div style={{ fontSize: 11 }}>
                Availability: {item.availability.slice(0, 2).map((row) => (
                  `${row.location_id} ${row.status}${row.quantity == null ? '' : ` (${row.quantity})`}`
                )).join(' · ')}
              </div>
            ) : null}
            </details>
            {projectionReady(item, onPropose) && (
              <div style={{ display: 'flex', gap: 5, marginTop: 7 }}>
                <input
                  aria-label={`Quantity for ${item.title}`}
                  type="number" min={1} max={500}
                  value={quantities[item.product.sku] || 1}
                  onChange={(event) => setQuantities((current) => ({
                    ...current,
                    [item.product.sku]: Math.max(1, Math.min(500, Number(event.target.value) || 1)),
                  }))}
                  style={{ width: 58 }}
                />
                <button type="button" onClick={() => onPropose?.(item, quantities[item.product.sku] || 1)} style={item.fit_status === 'qualified' ? { ...secondaryCommerceStyle, background: '#f15a0a', color: '#fff' } : secondaryCommerceStyle}>
                  {item.fit_status === 'qualified' ? 'Propose cart change' : 'Review option'}
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
      {!expanded && shelf.next_page.length > 0 && (
        <button type="button" style={{ ...secondaryCommerceStyle, marginTop: 8, padding: '5px 9px' }} onClick={() => setExpanded(true)}>
          + Show next {shelf.next_page.length}
        </button>
      )}
    </section>
  );
}

function projectionReady(item: ShelfProduct, onPropose?: (product: ShelfProduct, quantity: number) => void) {
  return Boolean(onPropose && item.product?.sku && item.fit_status !== 'failed');
}

function freshAvailableQuantity(item: ShelfProduct): number | null {
  const rows = (item.availability || []).filter((row) => (
    row.freshness_status === 'fresh' && row.quantity != null
    && ['in_stock', 'available'].includes(row.status)
  ));
  if (rows.length) return rows.reduce((sum, row) => sum + Number(row.quantity || 0), 0);
  return (item.availability || []).some((row) => (
    row.freshness_status === 'fresh'
    && (row.quantity === 0 || ['sold_out', 'built_to_order', 'at_supplier'].includes(row.status))
  )) ? 0 : null;
}
