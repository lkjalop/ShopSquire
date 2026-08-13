import type { ProcurementQuarantineView } from './procurementTraceProjection';

type Props = {
  procCase: any;
  journey: any[];
  quarantine: ProcurementQuarantineView;
  canSeeOperatorDraft: boolean;
  classNames: Record<string, string>;
  humanize: (value: unknown) => string;
};

export default function ProcurementAuditPanel({
  procCase, journey, quarantine, canSeeOperatorDraft, classNames, humanize,
}: Props) {
  const money = (cents: unknown) => typeof cents === 'number'
    ? `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
    : null;
  return (
    <>
      {canSeeOperatorDraft && quarantine.active && (
        <section data-testid="proc-supplier-quarantine" style={{ marginTop: 10, border: '1px solid #f59e0b',
          borderRadius: 8, padding: '10px 12px', background: '#fffbeb', color: '#78350f' }}>
          <div style={{ fontWeight: 700 }}>Supplier response quarantined</div>
          <div style={{ marginTop: 4 }}>No quote, price, inventory, economics, payment, or procurement state was applied.</div>
          <div className={classNames.kvRow}><span>Supplier domain</span><span>{quarantine.senderDomain}</span></div>
          <div className={classNames.kvRow}><span>Containment reason</span><span>{humanize(quarantine.reason)}</span></div>
          <div className={classNames.kvRow}><span>Security decision</span><span>{humanize(quarantine.severity)} - {humanize(quarantine.route)}</span></div>
          {quarantine.securityReasons.length > 0 && (
            <div className={classNames.kvRow}><span>Recorded evidence</span><span>{quarantine.securityReasons.map(humanize).join(', ')}</span></div>
          )}
          <div className={classNames.kvRow}><span>When</span><span className={classNames.mono}>
            {quarantine.timestamp ? quarantine.timestamp.replace('T', ' ').slice(0, 19) : 'not recorded'}
          </span></div>
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid #fde68a' }}>
            <strong>Operator actions:</strong> verify the supplier out of band, inspect Email Security evidence,
            and retain quarantine until an authorized review records a resolution.
          </div>
        </section>
      )}
      {procCase && journey.length > 0 && (
        <details data-testid="proc-audit-trail" style={{ marginTop: 10, border: '1px solid #d1d5db', borderRadius: 8, padding: '8px 10px' }} open>
          <summary style={{ cursor: 'pointer', fontWeight: 700 }}>
            Procurement audit trail <span style={{ fontWeight: 500, color: '#6b7280' }}>({journey.length} state transitions · bitemporal)</span>
          </summary>
          <table className={classNames.table} style={{ marginTop: 8 }}>
            <thead><tr><th>State</th><th>Event</th><th>Actor</th><th>When</th></tr></thead>
            <tbody>{journey.map((state: any, index: number) => (
              <tr key={state?.id || index}>
                <td>{String(state.state || '').replace(/_/g, ' ')}</td>
                <td>{state.event}{state.reason_code ? ` · ${state.reason_code}` : ''}</td>
                <td>{state.actor_type === 'human_operator' ? 'Human · ' : ''}{state.actor_id || state.actor_type || '—'}</td>
                <td className={classNames.mono} style={{ fontSize: 11 }}>
                  {String(state.valid_from || '').replace('T', ' ').slice(0, 19)}{state.valid_to == null ? ' · current' : ''}
                </td>
              </tr>
            ))}</tbody>
          </table>
          {money(procCase?.state_json?.split?.subtotal_cents) && (
            <div className={classNames.kvRow} style={{ marginTop: 6 }}><span>Order subtotal</span><span>{money(procCase.state_json.split.subtotal_cents)}</span></div>
          )}
        </details>
      )}
    </>
  );
}
