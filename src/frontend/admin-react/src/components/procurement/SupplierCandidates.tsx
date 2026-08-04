/** SupplierCandidates — read-only review prefill: the ranked, confidence-scored, provenance-tagged
 *  approved-supplier shortlist for the case's SKU. Helps the operator review + pick the recipient faster
 *  and safer BEFORE drafting. Contacts are resolved server-side from the allowlist/KYV (never buyer text);
 *  this surface never sends. Presentational. */
import React from 'react';
import type { SupplierCandidate } from '../../api';

const _money = (c?: number | null) => (c == null ? '—' : `$${(c / 100).toFixed(0)}`);
const _pct = (r?: number | null) => (r == null ? '—' : `${Math.round(r * 100)}%`);

const FLAG_LABEL: Record<string, string> = {
  no_verified_contact: 'no verified contact',
  no_prior_dealings: 'no prior dealings',
  high_risk: 'high risk',
};

export function SupplierCandidates({ candidates }: { candidates: SupplierCandidate[] }) {
  if (!candidates || candidates.length === 0) return null;
  return (
    <details open data-testid="op-supplier-candidates" style={{ margin: '8px 0' }}>
      <summary>Approved suppliers for this SKU ({candidates.length}) — review prefill</summary>
      <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
        {candidates.map((c) => {
          const conf = Math.max(0, Math.min(1, c.confidence || 0));
          return (
            <div key={c.supplier_id} data-testid="op-candidate"
                 style={{ padding: 8, borderRadius: 8, background: '#fff',
                          border: `1px solid ${c.recommended ? '#16a34a' : 'var(--border)'}` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <strong>{c.legal_name}</strong>
                {c.recommended && (
                  <span data-testid="op-candidate-recommended"
                        style={{ padding: '1px 6px', borderRadius: 4, fontSize: 11, fontWeight: 700,
                                 background: '#dcfce7', color: '#166534' }}>RECOMMENDED</span>
                )}
                <span style={{ marginLeft: 'auto', fontSize: 12, color: '#6b7280' }}>
                  confidence {Math.round(conf * 100)}%
                </span>
              </div>
              {/* confidence bar */}
              <div style={{ height: 4, background: '#eef2ff', borderRadius: 2, margin: '4px 0' }}>
                <div style={{ width: `${conf * 100}%`, height: 4, borderRadius: 2,
                              background: conf >= 0.66 ? '#16a34a' : conf >= 0.33 ? '#d97706' : '#dc2626' }} />
              </div>
              <div data-testid="op-candidate-contact" style={{ fontSize: 13 }}>
                {c.contact_email || <em style={{ color: '#b45309' }}>contact not verified</em>}
                <span style={{ color: '#6b7280' }}> · {c.domain}</span>
              </div>
              <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
                on-time {_pct(c.on_time_rate)} · reliability {_pct(c.reliability)} · lead {c.lead_time_days ?? '—'}d
                · {c.prior_dealings} prior {c.prior_dealings === 1 ? 'order' : 'orders'}
                {c.last_invoice_cents != null ? ` · last invoice ${_money(c.last_invoice_cents)}` : ''}
                · risk {c.risk_tier}
              </div>
              {c.flags && c.flags.length > 0 && (
                <div style={{ marginTop: 4 }}>
                  {c.flags.map((f) => (
                    <span key={f} data-testid="op-candidate-flag"
                          style={{ marginRight: 4, padding: '0 5px', borderRadius: 4, fontSize: 10,
                                   fontWeight: 700, background: '#fee2e2', color: '#991b1b' }}>
                      ⚠ {FLAG_LABEL[f] || f}
                    </span>
                  ))}
                </div>
              )}
              <small style={{ color: '#9ca3af' }}>
                source: {c.provenance?.contact_email || 'kyv'} · {c.provenance?.domain || 'allowlist'}
              </small>
            </div>
          );
        })}
      </div>
      <small style={{ color: '#6b7280' }}>
        Resolved from the approved-supplier allowlist + verified vendor registry — never from buyer input.
        Review prefill only; drafting + sending still require your approval.
      </small>
    </details>
  );
}

export default SupplierCandidates;
