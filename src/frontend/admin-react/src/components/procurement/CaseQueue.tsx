/** CaseQueue — the operator procurement QUEUE: search + status chips + the case list (extracted from
 *  ProcurementCases). Turns the raw table into a filterable queue. */
import React, { useMemo, useState } from 'react';
import type { FulfillmentCaseRow } from '../../api';

const STATUS_CHIPS = ['all', 'awaiting buyer', 'needs approval', 'quoting', 'options', 'PO', 'done'] as const;

function matchesChip(status: string, chip: string): boolean {
  const s = (status || '').toLowerCase();
  switch (chip) {
    case 'all': return true;
    case 'awaiting buyer': return s.includes('awaiting_buyer') || s === 'new' || s.includes('availability');
    case 'needs approval': return s.includes('awaiting_approval') || s.includes('approval_required') || s.includes('approved_to_send');
    case 'quoting': return s.includes('quote');
    case 'options': return s.includes('options') || s.includes('selected');
    case 'PO': return s.includes('procurement') || s.includes('ready_to_ship') || s.includes('partially');
    case 'done': return s.includes('completed') || s.includes('blocked') || s.includes('declined') || s.includes('quarantined') || s.includes('expired');
    default: return true;
  }
}

export function CaseQueue({ cases, sel, onSelect, onRefresh }: {
  cases: FulfillmentCaseRow[];
  sel: string;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}) {
  const [q, setQ] = useState('');
  const [chip, setChip] = useState<string>('all');

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    return cases.filter((c) =>
      matchesChip(c.status || '', chip)
      && (!term
        || c.case_id.toLowerCase().includes(term)
        || (c.status || '').toLowerCase().includes(term)
        || (c.requested_by || '').toLowerCase().includes(term)
        || (c.source_trace_id || '').toLowerCase().includes(term)));
  }, [cases, q, chip]);

  return (
    <aside data-testid="op-queue" style={{ minWidth: 280 }}>
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
      <table>
        <thead><tr><th>Case</th><th>Status</th></tr></thead>
        <tbody>
          {filtered.map((c) => (
            <tr key={c.case_id} data-testid="op-queue-row" onClick={() => onSelect(c.case_id)}
                style={{ cursor: 'pointer', fontWeight: c.case_id === sel ? 700 : 400 }}>
              <td>{c.case_id.slice(0, 8)}</td>
              <td>{c.status?.replace(/_/g, ' ').toLowerCase()}</td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr><td colSpan={2}><em>{cases.length ? 'no matches' : 'no cases'}</em></td></tr>
          )}
        </tbody>
      </table>
      <small style={{ color: '#6b7280' }} data-testid="op-queue-count">{filtered.length} of {cases.length}</small>
    </aside>
  );
}

export default CaseQueue;
