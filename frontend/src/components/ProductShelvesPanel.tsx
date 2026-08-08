import React from 'react';

type ShelfProduct = {
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
  freshness_status?: string;
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
};

const money = (value: number, currency: string) => new Intl.NumberFormat('en-AU', {
  style: 'currency', currency: currency || 'AUD', maximumFractionDigits: 0,
}).format(value / 100);

export default function ProductShelvesPanel({ projection, onPropose }: {
  projection: ProductShelfProjection;
  onPropose?: (sku: string, quantity: number) => void;
}) {
  if (!projection?.shelves?.length) return null;
  return (
    <section data-testid="product-shelves" aria-label="Provisional product shelves" style={{ padding: 12 }}>
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
          )) : <div style={{ fontSize: 12, marginTop: 4 }}>{projection.evidence_status === 'researched'
            ? 'Ranking order did not change; evidence status and visible gaps were updated.'
            : 'No product requirements were established, so research did not authorize a verified rerank.'}</div>}
        </section>
      )}
      {projection.shelves.map((shelf) => (
        <Shelf key={shelf.shelf_id} shelf={shelf} onPropose={onPropose} />
      ))}
    </section>
  );
}

function Shelf({ shelf, onPropose }: { shelf: ProductShelf; onPropose?: (sku: string, quantity: number) => void }) {
  const [expanded, setExpanded] = React.useState(false);
  const [quantities, setQuantities] = React.useState<Record<string, number>>({});
  const products = expanded ? [...shelf.initial, ...shelf.next_page] : shelf.initial;
  const band = shelf.budget_band === 'within_budget' ? 'Within budget'
    : shelf.budget_band === 'stretch' ? 'Stretch' : 'Best fit';
  return (
    <section data-testid={`product-shelf-${shelf.shelf_id}`} style={{ marginBottom: 16 }}>
      <h3 style={{ margin: '0 0 3px', fontSize: 15 }}>{shelf.scope_label}</h3>
      <div style={{ fontSize: 12, marginBottom: 7 }}>{band}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 7 }}>
        {products.map((item) => (
          <article key={item.identity_key} style={{ border: '1px solid #cbd5e1', borderRadius: 8, padding: 8 }}>
            <strong style={{ fontSize: 12 }}>{item.title}</strong>
            <div style={{ marginTop: 6 }}>{money(item.price_cents, item.currency)}</div>
            <div style={{ marginTop: 4, fontSize: 11 }}>Fit: {item.fit_status}</div>
            <div style={{ fontSize: 11 }}>MPN: {item.product.identifier || 'unknown'}</div>
            {item.meets?.length ? <div style={{ fontSize: 11 }}>Meets: {item.meets.join(', ')}</div> : null}
            {item.conditional?.length ? <div style={{ fontSize: 11 }}>Conditional: {item.conditional.join(', ')}</div> : null}
            {item.unknowns?.length ? <div style={{ fontSize: 11 }}>Unknown: {item.unknowns.join(', ')}</div> : null}
            {item.misses?.length ? <div style={{ fontSize: 11 }}>Misses: {item.misses.join(', ')}</div> : null}
            <div style={{ fontSize: 11 }}>Evidence freshness: {item.freshness_status || 'unknown'}</div>
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
                <button type="button" onClick={() => onPropose?.(item.product.sku, quantities[item.product.sku] || 1)} style={{ background: item.fit_status === 'qualified' ? '#f15a0a' : '#fff', color: item.fit_status === 'qualified' ? '#fff' : '#173b64', border: `1px solid ${item.fit_status === 'qualified' ? '#f15a0a' : '#173b64'}`, borderRadius: 6, padding: '6px 9px' }}>
                  {item.fit_status === 'qualified' ? 'Propose cart change' : 'Review option'}
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
      {!expanded && shelf.next_page.length > 0 && (
        <button type="button" style={{ marginTop: 8, background: 'transparent', color: '#173b64', border: '1px solid #94a3b8', borderRadius: 6, padding: '5px 9px' }} onClick={() => setExpanded(true)}>
          + Show next {shelf.next_page.length}
        </button>
      )}
    </section>
  );
}

function projectionReady(item: ShelfProduct, onPropose?: (sku: string, quantity: number) => void) {
  return Boolean(onPropose && item.product?.sku && item.fit_status !== 'failed');
}
