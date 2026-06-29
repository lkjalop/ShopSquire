// "Create from a mixed order" — paste a buyer's multi-line request ("15 laptops + 10 monitors + 5
// headsets"), the backend parses → resolves SKUs → plans the supplier split → creates ONE case per
// supplier (each at GATE 1, no supplier contacted). Shows the result grouped by supplier
// ("2 cases: CreatorFleet + PeriLink"). Read-then-create; no email is sent.
import React, { useState } from 'react';
import { fcFromOrder, type FromOrderResult } from '../../api';

export default function CreateFromOrder({ onCreated }: { onCreated?: () => void }) {
  const [q, setQ] = useState('');
  const [result, setResult] = useState<FromOrderResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    if (!q.trim() || busy) return;
    setBusy(true); setErr(null); setResult(null);
    try {
      const r = await fcFromOrder(q.trim());
      setResult(r);
      onCreated?.();
    } catch (e: any) {
      setErr(e?.message || 'failed to create cases');
    } finally {
      setBusy(false);
    }
  };

  return (
    <details data-testid="create-from-order"
             style={{ marginBottom: 12, padding: '8px 12px', borderRadius: 8, border: '1px solid #e5e7eb', background: '#f9fafb' }}>
      <summary style={{ fontWeight: 700, cursor: 'pointer' }}>Create from a mixed order</summary>
      <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'flex-start' }}>
        <textarea data-testid="cfo-input" value={q} onChange={(e) => setQ(e.target.value)} rows={2}
                  placeholder="e.g. 15 laptops + 10 monitors + 5 headsets"
                  style={{ flex: 1, padding: 8, borderRadius: 6, border: '1px solid #d1d5db', resize: 'vertical' }} />
        <button className="btn" data-testid="cfo-run" disabled={busy || !q.trim()} onClick={run}>
          {busy ? 'Creating…' : 'Plan & create grouped cases'}
        </button>
      </div>
      {err && <div role="alert" style={{ color: 'crimson', marginTop: 6, fontSize: 13 }}>{err}</div>}
      {result && (
        <div data-testid="cfo-result" style={{ marginTop: 8 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>
            Created {result.case_count} case{result.case_count === 1 ? '' : 's'} · order {String(result.order_group_id).slice(0, 14)}
          </div>
          {(result.cases || []).map((c) => (
            <div key={c.case_id} style={{ padding: '6px 8px', borderRadius: 6, background: '#fff',
                 border: '1px solid #eee', marginBottom: 4, fontSize: 13 }}>
              <strong>{c.supplier_name || c.recipient_domain || c.supplier_ref}</strong>{' — '}
              {(c.lines || []).map((l) => `${l.item_ref}×${l.quantity}`).join(', ')}{' '}
              <span style={{ color: '#6b7280' }}>({c.total_quantity} units · case {c.case_id.slice(0, 8)})</span>
            </div>
          ))}
          <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 4 }}>
            Each case waits at GATE 1 (buyer commitment) — no supplier has been contacted.
          </div>
        </div>
      )}
    </details>
  );
}
