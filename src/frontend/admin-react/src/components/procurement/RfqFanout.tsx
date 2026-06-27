/** RfqFanout — competitive multi-supplier RFQ (Phase 1, operator decision-support).
 *  Shows the caged draft preview per top-N approved supplier (these never send — the operator still
 *  approves each send through GATE 2), and lets the operator key in returned quotes and rank them by the
 *  backend's vertical-blind composite (price · lead · reliability). The compare call is injected so the
 *  component is pure/testable; the container wires the real fcCompareQuotes. */
import React, { useMemo, useState } from 'react';
import type { QuoteInput, RankedQuote, RfqFanoutDraft } from '../../api';

type CompareResult = { ranked: RankedQuote[]; recommended: RankedQuote | null; considered: number; excluded: number };

const _money = (c?: number | null) => (c == null ? '—' : `$${(c / 100).toFixed(0)}`);
const _gateColor = (d?: string) => (d === 'allow' ? '#166534' : d === 'block' ? '#991b1b' : '#92400e');

export function RfqFanout({
  drafts,
  onCompare,
}: {
  drafts: RfqFanoutDraft[];
  onCompare: (quotes: QuoteInput[]) => Promise<CompareResult>;
}) {
  // one editable quote row per drafted supplier (recipient prefilled; operator fills price/lead/reliability)
  const initial = useMemo(
    () => drafts.map((d) => ({ recipient_domain: d.recipient_domain, supplier_ref: d.recipient_ref,
                               unit_price_cents: '', lead_time_days: '', reliability: '' })),
    [drafts],
  );
  const [rows, setRows] = useState(initial);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => { setRows(initial); setResult(null); }, [initial]);

  if (!drafts || drafts.length === 0) return null;

  const setCell = (i: number, k: string, v: string) =>
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, [k]: v } : r)));

  const compare = async () => {
    setBusy(true); setError(null);
    try {
      const quotes: QuoteInput[] = rows
        .filter((r) => String(r.unit_price_cents).trim() !== '')
        .map((r) => ({
          supplier_ref: r.supplier_ref, recipient_domain: r.recipient_domain,
          unit_price_cents: Number(r.unit_price_cents),
          lead_time_days: r.lead_time_days === '' ? null : Number(r.lead_time_days),
          reliability: r.reliability === '' ? null : Number(r.reliability),
        }));
      setResult(await onCompare(quotes));
    } catch (e: any) {
      setError(e?.message || 'compare failed');
    } finally {
      setBusy(false);
    }
  };

  const recDomain = result?.recommended?.recipient_domain;

  return (
    <details open data-testid="op-rfq-fanout" style={{ margin: '8px 0' }}>
      <summary>Competitive RFQ — {drafts.length} approved supplier{drafts.length > 1 ? 's' : ''} (preview only, never sends)</summary>

      {/* caged draft preview per supplier */}
      <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
        {drafts.map((d) => (
          <div key={d.recipient_ref + d.recipient_domain} data-testid="op-rfq-draft"
               style={{ padding: 8, borderRadius: 8, background: '#fff', border: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <strong>{d.recipient_domain}</strong>
              <span style={{ fontSize: 12, color: '#6b7280' }}>{d.recipient_email || 'contact via domain'}</span>
              <span style={{ marginLeft: 'auto', fontSize: 12, color: '#6b7280' }}>
                confidence {Math.round((d.confidence || 0) * 100)}%
              </span>
              <span data-testid="op-rfq-gate" style={{ fontSize: 11, fontWeight: 700, color: _gateColor(d.send_gate?.decision) }}>
                gate: {d.send_gate?.decision || 'n/a'}
              </span>
            </div>
            <div style={{ fontSize: 12, color: '#374151', marginTop: 2 }}>{d.subject}</div>
          </div>
        ))}
      </div>

      {/* quote entry + comparison */}
      <div style={{ marginTop: 10 }}>
        <table style={{ width: '100%', fontSize: 12 }}>
          <thead>
            <tr><th style={{ textAlign: 'left' }}>Supplier</th><th>Unit price (¢)</th><th>Lead (days)</th><th>Reliability 0–1</th></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.recipient_domain} data-testid="op-rfq-quote-row">
                <td>{r.recipient_domain}</td>
                <td><input data-testid="op-rfq-price" style={{ width: 90 }} value={r.unit_price_cents}
                           onChange={(e) => setCell(i, 'unit_price_cents', e.target.value)} /></td>
                <td><input data-testid="op-rfq-lead" style={{ width: 60 }} value={r.lead_time_days}
                           onChange={(e) => setCell(i, 'lead_time_days', e.target.value)} /></td>
                <td><input data-testid="op-rfq-rel" style={{ width: 60 }} value={r.reliability}
                           onChange={(e) => setCell(i, 'reliability', e.target.value)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <button data-testid="op-rfq-compare" onClick={compare} disabled={busy} style={{ marginTop: 6 }}>
          {busy ? 'Comparing…' : 'Compare quotes'}
        </button>
        {error && <span role="alert" style={{ color: 'crimson', marginLeft: 8 }}>{error}</span>}
      </div>

      {result && (
        <div data-testid="op-rfq-result" style={{ marginTop: 8 }}>
          <div style={{ fontSize: 12, color: '#6b7280' }}>
            {result.considered} compared{result.excluded ? `, ${result.excluded} excluded (no price)` : ''}
          </div>
          {result.ranked.map((q, idx) => {
            const isRec = q.recipient_domain === recDomain;
            return (
              <div key={(q.recipient_domain || '') + idx} data-testid="op-rfq-ranked"
                   style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 8px', borderRadius: 6, marginTop: 4,
                            background: isRec ? '#dcfce7' : '#f8fafc', border: isRec ? '1px solid #16a34a' : '1px solid var(--border)' }}>
                <strong>#{idx + 1}</strong>
                <span>{q.recipient_domain}</span>
                <span style={{ color: '#6b7280' }}>{_money(q.unit_price_cents)} · {q.lead_time_days ?? '—'}d · rel {q.reliability ?? '—'}</span>
                {isRec && <span data-testid="op-rfq-recommended" style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 700, color: '#166534' }}>RECOMMENDED</span>}
                <span style={{ marginLeft: isRec ? 8 : 'auto', fontSize: 11, color: '#6b7280' }}>score {q.composite}</span>
              </div>
            );
          })}
        </div>
      )}
    </details>
  );
}

export default RfqFanout;
