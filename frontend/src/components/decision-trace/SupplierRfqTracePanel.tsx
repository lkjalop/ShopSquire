import { procurementGateDisplay } from '../../lib/procurementGateDisplay';

type Props = {
  cases: any[];
  activeCase: any;
  draft: any;
  procurementTrace: any;
  history: any;
  integrityEvents: any[];
  canSeeOperatorDraft: boolean;
  classNames: Record<string, string>;
};

function orderingTerms(draft: any): string {
  const terms = draft?.supplier_terms || {};
  return [
    terms.moq != null ? `MOQ ${terms.moq}` : null,
    terms.lead_time_days != null ? `${terms.lead_time_days}d lead` : null,
    terms.min_order_value_cents ? `min $${Math.round(terms.min_order_value_cents / 100)}` : null,
    terms.contract_status ? String(terms.contract_status) : null,
    (terms.price_breaks || []).length
      ? `breaks: ${(terms.price_breaks || []).map((row: any) => `${row.min_qty}→${row.discount_pct}%`).join(', ')}`
      : null,
  ].filter(Boolean).join(' · ');
}

function channelLabel(plan: any): string {
  if (plan?.requires_human) return `${String(plan.channel || '').toUpperCase()} · human-only`;
  if (plan?.integration_kind) return `${String(plan.integration_kind).toUpperCase()} integration handoff`;
  return `${String(plan?.channel || 'email')} · agent drafts · human sends (GATE 2)`;
}

export default function SupplierRfqTracePanel({
  cases, activeCase, draft, procurementTrace, history, integrityEvents,
  canSeeOperatorDraft, classNames,
}: Props) {
  const gate = procurementGateDisplay(draft?.send_gate || draft?.gate);
  const hasRfq = cases.length > 0 || Boolean(activeCase && draft);
  return <>
    {canSeeOperatorDraft && history?.case_count > 1 && <div data-testid="proc-amendment-history" style={{ border: '1px solid #f59e0b', background: '#fffbeb', borderRadius: 8, padding: '8px 10px', marginBottom: 12, fontSize: 13 }}>
      <div style={{ fontWeight: 700, color: '#92400e' }}>RFQ revision {history.case_count} - prior draft superseded</div>
      <div style={{ marginTop: 4, color: '#4b5563' }}>{history?.draft_diff?.fields?.subject ? <><span className={classNames.mono}>{history.draft_diff.fields.subject.from}</span><br /><span>→ </span><span className={classNames.mono}>{history.draft_diff.fields.subject.to}</span></> : 'The active supplier draft was regenerated from the amended cart.'}</div>
      <div style={{ marginTop: 4, color: '#6b7280', fontSize: 12 }}>{history?.draft_diff?.body_changed ? 'Draft body changed.' : 'Draft metadata changed.'} The prior content hash remains in the bitemporal audit; nothing was sent.</div>
    </div>}

    {cases.length > 1 && <div data-testid="proc-multi-rfq" style={{ marginBottom: 12 }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{cases.length} supplier RFQs drafted — one per supplier · human-gated · nothing sent</div>
      {cases.map((procCase: any, index: number) => {
        const item = procCase?.state_json?.draft || {};
        return <details key={procCase.case_id || index} data-testid={`proc-rfq-${index}`} style={{ border: '1px solid #d1d5db', borderRadius: 8, padding: '8px 10px', marginBottom: 6 }} open={index === 0}>
          <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Supplier {index + 1} of {cases.length} — {item.recipient_ref || '—'} <span style={{ marginLeft: 8, fontSize: 12, color: '#6b7280' }}>{channelLabel(item.channel_plan)}</span></summary>
          <div style={{ marginTop: 8, fontSize: 13 }}>
            {item.recipient_domain && <div className={classNames.kvRow}><span>Domain</span><span className={classNames.mono}>{item.recipient_domain}</span></div>}
            {orderingTerms(item) && <div className={classNames.kvRow}><span>Ordering terms</span><span>{orderingTerms(item)}</span></div>}
            {item.channel_plan?.rationale && <div className={classNames.kvRow}><span>Why this channel</span><span>{item.channel_plan.rationale}</span></div>}
            <div className={classNames.kvRow}><span>Subject</span><span>{item.subject || '—'}</span></div>
            {canSeeOperatorDraft ? <><div style={{ marginTop: 6, fontWeight: 600, color: '#6b7280' }}>Body (quote request — no price is ever stated to the supplier)</div><pre style={{ whiteSpace: 'pre-wrap', background: '#f9fafb', padding: 8, maxHeight: 220, overflow: 'auto' }}>{item.body || '(not drafted yet)'}</pre></> : <div className={classNames.empty}>Human-gated — sign in with an operator key to view the drafted email.</div>}
          </div>
        </details>;
      })}
    </div>}

    {cases.length <= 1 && activeCase && draft && canSeeOperatorDraft && <div data-testid="proc-drafted-rfq" style={{ border: '1px solid #d1d5db', borderRadius: 10, padding: '10px 12px', fontSize: 13 }}>
      <div style={{ fontWeight: 700 }}>Drafted supplier RFQ — {String(activeCase.state || '').replace(/_/g, ' ').toLowerCase()} <span style={{ marginLeft: 8, color: '#b45309', fontSize: 12 }}>human-gated · not sent</span></div>
      <div className={classNames.kvRow}><span>To (supplier)</span><span data-testid="proc-rfq-recipient">{draft.recipient_ref || '—'}{draft.recipient_domain ? ` · ${draft.recipient_domain}` : ''}</span></div>
      {draft.recipient_email && <div className={classNames.kvRow}><span>Contact</span><span className={classNames.mono}>{draft.recipient_email}</span></div>}
      {draft.channel_plan && <div className={classNames.kvRow} data-testid="proc-supplier-channel"><span>Preferred channel</span><span>{channelLabel(draft.channel_plan)}</span></div>}
      {draft.channel_plan?.rationale && <div className={classNames.kvRow}><span>Why this channel</span><span>{draft.channel_plan.rationale}</span></div>}
      {orderingTerms(draft) && <div className={classNames.kvRow} data-testid="proc-supplier-terms"><span>Ordering terms</span><span>{orderingTerms(draft)}</span></div>}
      {draft.commercial_scope?.quantity != null && <div className={classNames.kvRow}><span>RFQ quantity</span><span>{draft.commercial_scope.quantity} supplier-shortfall unit(s)</span></div>}
      {activeCase?.state_json?.availability?.requested_qty != null && <div className={classNames.kvRow}><span>Cart demand</span><span>{activeCase.state_json.availability.requested_qty} requested · {activeCase.state_json.availability.in_stock ?? 0} in stock · {activeCase.state_json.availability.shortfall ?? draft.commercial_scope?.quantity ?? 0} sourced</span></div>}
      {Array.isArray(activeCase?.state_json?.availability?.lines) && activeCase.state_json.availability.lines.map((line: any) => <div key={line.sku} data-testid={`proc-availability-${line.sku}`} style={{ borderTop: '1px solid #e5e7eb', marginTop: 6, paddingTop: 6 }}><div className={classNames.kvRow}><span>Combined availability</span><span>{line.local_now ?? 0} local · {line.network_transfer ?? 0} network transfer · {line.supplier_rfq_qty ?? 0} RFQ</span></div><div style={{ color: '#6b7280', fontSize: 12 }}>Supplier availability is unconfirmed until the RFQ receives a response.</div></div>)}
      <div className={classNames.kvRow}><span>Subject</span><span data-testid="proc-rfq-subject">{draft.subject || '—'}</span></div>
      {draft.content_hash && <div className={classNames.kvRow}><span>Content hash</span><span className={classNames.mono}>{draft.content_hash}</span></div>}
      {(draft.send_gate || draft.gate) && <div className={classNames.kvRow}><span>Send gate</span><span>{gate.label}</span></div>}
      {gate.reasons.length > 0 && <div data-testid="proc-send-gate-actions" style={{ margin: '6px 0', padding: '8px 10px', border: '1px solid #f59e0b', background: '#fffbeb', borderRadius: 6 }}><strong>Resolve before supplier approval</strong>{gate.reasons.map(reason => <div key={reason.code} style={{ marginTop: 5 }}><strong>{reason.label}</strong> {reason.action}</div>)}</div>}
      <div style={{ marginTop: 6, fontWeight: 600, color: '#6b7280' }}>Body (a quote request — no price is ever stated to the supplier)</div>
      <pre data-testid="proc-rfq-body" style={{ whiteSpace: 'pre-wrap', background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6, padding: 8, maxHeight: 260, overflow: 'auto' }}>{draft.body || '(not drafted yet)'}</pre>
    </div>}

    {cases.length <= 1 && activeCase && procurementTrace && !canSeeOperatorDraft && <div data-testid="proc-rfq-safe-summary" style={{ border: '1px solid #d1d5db', borderRadius: 8, padding: '9px 11px', marginTop: 8, fontSize: 13 }}>
      <div style={{ fontWeight: 700 }}>Supplier RFQ drafted <span style={{ color: '#b45309', fontSize: 12 }}>human-gated · not sent</span></div>
      <div className={classNames.kvRow}><span>RFQ quantity</span><span>{procurementTrace.quantity ?? '—'} supplier-shortfall unit(s)</span></div>
      {procurementTrace.channel && <div className={classNames.kvRow}><span>Preferred channel</span><span>{String(procurementTrace.channel)}</span></div>}
      <div className={classNames.empty}>Supplier contact, ordering terms, and message content are operator-only.</div>
    </div>}
    {cases.length <= 1 && activeCase && !draft && !canSeeOperatorDraft && String(activeCase.state || '').toUpperCase().includes('DRAFTED') && <div className={classNames.empty}>A supplier RFQ was drafted, but supplier contact and message content are operator-only.</div>}

    {hasRfq && <div data-testid="proc-readonly-note" style={{ marginTop: 8, marginBottom: 12, fontSize: 12, color: '#6b7280', borderTop: '1px dashed #e5e7eb', paddingTop: 6 }}>Read-only trace — supplier or RFQ edits happen in the operator console, void prior approval, and re-lock GATE 2. Nothing is sent from here.</div>}

    {integrityEvents.length > 0 && <div data-testid="proc-integrity-guard" style={{ border: '1px solid #16a34a', background: '#f0fdf4', borderRadius: 10, padding: '10px 12px', fontSize: 13, marginBottom: 12 }}>
      <div style={{ fontWeight: 700, color: '#166534' }}>Outbound integrity guard — {integrityEvents.length} supplier message{integrityEvents.length > 1 ? 's' : ''} quarantined before send</div>
      <div style={{ color: '#166534', marginBottom: 6 }}>ShopSquire scanned its own drafted supplier message and did not relay it.</div>
      {integrityEvents.map((event, index) => { const payload = event?.payload || {}; const action = String(payload.action || 'block'); return <div key={event?.id || index}><strong>{action === 'block' ? 'BLOCKED' : 'HELD FOR REVIEW'}</strong>{payload.recipient_domain ? ` → ${payload.recipient_domain}` : ''}{Array.isArray(payload.findings) && payload.findings.length ? ` · ${payload.findings.join(', ')}` : ''}</div>; })}
    </div>}
  </>;
}
