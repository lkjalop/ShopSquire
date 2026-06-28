/** CaseQueue — the operator procurement QUEUE: search + status chips + the case list (extracted from
 *  ProcurementCases). Turns the raw table into a filterable queue. */
import React, { useMemo, useState } from 'react';
import type { FulfillmentCaseRow } from '../../api';

const STATUS_CHIPS = ['needs action', 'all', 'awaiting buyer', 'needs approval', 'quoting', 'options', 'PO', 'done'] as const;

// States that require an operator to do something next (the default workbench view). Excludes terminal
// states and states waiting on the buyer/supplier. NO_APPROVED_SUPPLIER is included — it needs a fix.
function isNeedsAction(s: string): boolean {
  // awaiting_buyer_commitment is INCLUDED: a buyer-initiated bulk request lands here and the operator
  // should see it in the default workbench (to qualify the buyer / draft), not have it hidden under a tab.
  return ['awaiting_buyer_commitment', 'committed', 'quote_drafted', 'awaiting_approval', 'approved_to_send',
          'quote_received', 'quote_validated', 'selected', 'procurement_approval_required',
          'no_approved_supplier']
    .some((t) => s.includes(t));
}

function isBlocked(status: string): boolean {
  return (status || '').toLowerCase().includes('no_approved_supplier');
}

function matchesChip(status: string, chip: string): boolean {
  const s = (status || '').toLowerCase();
  switch (chip) {
    case 'all': return true;
    case 'needs action': return isNeedsAction(s);
    case 'awaiting buyer': return s.includes('awaiting_buyer') || s === 'new' || s.includes('availability');
    case 'needs approval': return s.includes('awaiting_approval') || s.includes('approval_required') || s.includes('approved_to_send');
    case 'quoting': return s.includes('quote');
    case 'options': return s.includes('options') || s.includes('selected');
    case 'PO': return s.includes('procurement') || s.includes('ready_to_ship') || s.includes('partially');
    case 'done': return s.includes('completed') || s.includes('blocked') || s.includes('declined') || s.includes('quarantined') || s.includes('expired');
    default: return true;
  }
}

function shortWhen(ts?: string | null): string {
  if (!ts) return '';
  // backend sends ISO-ish timestamps; show just the date+HH:MM, no TZ parsing risk
  const m = String(ts).match(/(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
  return m ? `${m[1].slice(5)} ${m[2]}` : String(ts).slice(0, 16);
}

export function CaseQueue({ cases, sel, onSelect, onRefresh }: {
  cases: FulfillmentCaseRow[];
  sel: string;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}) {
  const [q, setQ] = useState('');
  const [chip, setChip] = useState<string>('needs action');  // default to the operator workbench view

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    return cases
      .filter((c) =>
        matchesChip(c.status || '', chip)
        && (!term
          || c.case_id.toLowerCase().includes(term)
          || (c.status || '').toLowerCase().includes(term)
          || (c.item_ref || '').toLowerCase().includes(term)
          || (c.requested_by || '').toLowerCase().includes(term)
          || (c.source_trace_id || '').toLowerCase().includes(term)))
      // newest-first explicitly (don't rely on server order surviving the filter)
      .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
  }, [cases, q, chip]);

  const blockedCount = useMemo(() => cases.filter((c) => isBlocked(c.status || '')).length, [cases]);

  return (
    <aside data-testid="op-queue" style={{ minWidth: 360 }}>
      <h3 style={{ marginBottom: 6 }}>Procurement queue <button onClick={onRefresh} title="Refresh">↻</button></h3>
      <input data-testid="op-queue-search" value={q} onChange={(e) => setQ(e.target.value)}
             placeholder="search case · status · buyer · trace" style={{ width: '100%', marginBottom: 6 }} />
      <div data-testid="op-queue-chips" style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
        {STATUS_CHIPS.map((ch) => (
          <button key={ch} data-testid={`op-chip-${ch.replace(/\s+/g, '-')}`} onClick={() => setChip(ch)}
                  style={{
                    padding: '2px 8px', borderRadius: 12, fontSize: 12, border: 'none', cursor: 'pointer',
                    background: chip === ch ? '#1e3a8a' : '#eef2ff', color: chip === ch ? '#fff' : '#1e3a8a',
                  }}>{ch}</button>
        ))}
      </div>
      {blockedCount > 0 && (
        <div data-testid="op-queue-blocked-warning"
             style={{ margin: '0 0 8px', padding: '4px 8px', borderRadius: 6, fontSize: 12, fontWeight: 700,
                      background: '#fee2e2', color: '#991b1b' }}>
          ⚠ {blockedCount} case{blockedCount > 1 ? 's' : ''} blocked: no approved supplier
        </div>
      )}
      <table>
        <thead><tr><th>Case</th><th>SKU</th><th>Qty</th><th>Status</th><th>Updated</th></tr></thead>
        <tbody>
          {filtered.map((c) => {
            const blocked = isBlocked(c.status || '');
            return (
              <tr key={c.case_id} data-testid="op-queue-row" onClick={() => onSelect(c.case_id)}
                  style={{ cursor: 'pointer', fontWeight: c.case_id === sel ? 700 : 400,
                           background: c.case_id === sel ? '#eef2ff' : undefined }}>
                <td>{c.case_id.slice(0, 8)}</td>
                <td data-testid="op-queue-row-sku" style={{ fontSize: 12 }}>{c.item_ref || '—'}</td>
                <td data-testid="op-queue-row-qty" style={{ fontSize: 12, textAlign: 'right' }}>{c.quantity ?? '—'}</td>
                <td>
                  {c.status?.replace(/_/g, ' ').toLowerCase()}
                  {blocked && (
                    <span data-testid="op-queue-row-blocked" title="No approved supplier for this SKU"
                          style={{ marginLeft: 6, padding: '0 5px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                                   background: '#fecaca', color: '#991b1b' }}>NO SUPPLIER</span>
                  )}
                </td>
                <td style={{ color: '#6b7280', fontSize: 11, whiteSpace: 'nowrap' }}>{shortWhen(c.updated_at)}</td>
              </tr>
            );
          })}
          {filtered.length === 0 && (
            <tr><td colSpan={5}><em>{cases.length ? 'no matches' : 'no cases'}</em></td></tr>
          )}
        </tbody>
      </table>
      <small style={{ color: '#6b7280' }} data-testid="op-queue-count">{filtered.length} of {cases.length}</small>
    </aside>
  );
}

export default CaseQueue;
