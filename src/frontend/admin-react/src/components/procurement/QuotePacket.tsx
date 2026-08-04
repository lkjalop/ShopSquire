/** QuotePacket — the parsed supplier quote + the resulting purchase order (extracted from
 *  ProcurementCases). Presentational. */
import React from 'react';

export function QuotePacket({ parsed, po, isDemoReply }: {
  parsed: Record<string, any>;
  po: Record<string, any>;
  isDemoReply: boolean;
}) {
  return (
    <>
      {parsed.quoted_quantity != null && (
        <details open data-testid="op-quote-packet">
          <summary>Parsed quote (confidence {parsed.confidence})
            {isDemoReply && (
              <span data-testid="op-demo-quote"
                    style={{ marginLeft: 8, padding: '1px 5px', background: '#dbeafe', color: '#1e3a8a',
                             borderRadius: 4, fontSize: 11, fontWeight: 700 }}>
                DEMO QUOTE RESPONSE
              </span>
            )}
          </summary>
          <div>Qty {parsed.quoted_quantity} · unit {parsed.unit_amount_cents} · dispatch {parsed.dispatch_ready_at} · expires {parsed.quote_expires_at}</div>
          {parsed.contradictory && <div style={{ color: 'orange' }}>⚠ contradictory quantity — review</div>}
          {Array.isArray(parsed.evidence_spans) && (
            <ul>{parsed.evidence_spans.map((s: any, i: number) => <li key={i}>{s.field}: “{s.text}”</li>)}</ul>
          )}
        </details>
      )}

      {po.status && (
        <details open data-testid="op-po-packet">
          <summary>Purchase order {po.po_ref ? `(${po.po_ref})` : '(proposed)'}</summary>
          {po.sandbox && <div style={{ color: '#b45309' }}>SANDBOX SUPPLIER — no real PO transmitted</div>}
          <div>Status <strong>{po.status}</strong> · qty {po.quantity}
            {po.total_amount_cents != null && <> · wholesale total {po.total_amount_cents}c</>}</div>
        </details>
      )}
    </>
  );
}

export default QuotePacket;
