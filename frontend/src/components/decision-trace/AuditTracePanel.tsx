import TemporalCacheTechnicalTrace from '../ProcurementOperationalTrace';

export default function AuditTracePanel({
  allocationView,
  loading,
  error,
  auditTrail,
  onRetry,
  classNames,
}: {
  allocationView: any;
  loading: boolean;
  error: string | null;
  auditTrail: any;
  onRetry: () => void;
  classNames: Record<string, string>;
}) {
  const s = classNames;
  return (
    <div className={s.summaryPane} data-testid="audit-trace-panel">
      <TemporalCacheTechnicalTrace allocationView={allocationView} />
      {loading && <div className={s.empty}>Loading audit trail...</div>}
      {!loading && error && <div className={s.empty} role="alert">{error} No decision state was changed. <button onClick={onRetry}>Retry</button></div>}
      {!loading && !auditTrail && !error && <div className={s.empty}>No audit trail data. Click the tab to fetch.</div>}
      {auditTrail && <>
        <div className={s.sectionTitle}>Bitemporal Decision Audit</div>
        <div className={s.kvRow}><span>Decisions</span><span>{auditTrail.decision_count}</span></div>
        <div className={s.kvRow}><span>Events</span><span>{auditTrail.event_count}</span></div>
        <div className={s.kvRow}><span>Hash Chain Length</span><span>{auditTrail.immutability?.chain_length}</span></div>
        <div className={s.kvRow}><span>Tip Hash</span><span className={s.mono}>{auditTrail.immutability?.tip_hash}</span></div>
        <div className={s.kvRow}><span>Chain Verified</span><span>{auditTrail.immutability?.verified ? '✅ Yes' : '⚠️ Not in this environment'}</span></div>
        {auditTrail.immutability?.reason && <div className={s.kvRow}><span>Why</span><span>{auditTrail.immutability.reason}</span></div>}
        {auditTrail.immutability?.persisted_chain && <div className={s.kvRow}><span>Persisted WORM chain</span><span>{auditTrail.immutability.persisted_chain.entries_checked} entries · anchor {auditTrail.immutability.persisted_chain.anchor_present ? 'present' : 'pending'}</span></div>}

        <div className={s.sectionTitle}>Storage &amp; Immutability</div>
        <div className={s.kvRow}><span>Backend</span><span>{auditTrail.storage?.backend}</span></div>
        <div className={s.kvRow}><span>Encryption at Rest</span><span>{auditTrail.storage?.encryption_at_rest ? 'Yes' : 'No'}</span></div>
        <div className={s.kvRow}><span>Backup</span><span>{auditTrail.storage?.backup_enabled ? 'Enabled' : 'Not configured'}</span></div>

        {(auditTrail.decisions || []).length > 0 && <>
          <div className={s.sectionTitle}>Component Decisions (Bitemporal)</div>
          <table className={s.smallTable}><thead><tr><th>Component</th><th>Valid From</th><th>Valid To</th><th>System From</th><th>Status</th><th>Approval</th></tr></thead><tbody>
            {(auditTrail.decisions || []).map((decision: any, index: number) => <tr key={index}>
              <td>{decision.agent_name}</td><td className={s.mono}>{decision.valid_from?.slice(0, 19)}</td>
              <td className={s.mono}>{decision.valid_to === 'infinity' ? '∞' : decision.valid_to?.slice(0, 19)}</td>
              <td className={s.mono}>{decision.system_from?.slice(0, 19)}</td><td>{decision.execution_status}</td>
              <td>{decision.approval_required ? '⚠️ Required' : '✅ Auto'}</td>
            </tr>)}
          </tbody></table>
        </>}

        <div className={s.sectionTitle}>Hash Chain (Tamper Evidence)</div>
        <div style={{ maxHeight: 200, overflow: 'auto' }}><table className={s.smallTable}><thead><tr><th>#</th><th>Type</th><th>Timestamp</th><th>Hash</th><th>Prev</th></tr></thead><tbody>
          {(auditTrail.hash_chain || []).slice(0, 50).map((item: any, index: number) => <tr key={index}>
            <td>{index + 1}</td><td>{item.type}</td><td className={s.mono}>{item.timestamp?.slice(0, 19) || '--'}</td><td className={s.mono}>{item.hash}</td><td className={s.mono}>{item.prev_hash}</td>
          </tr>)}
        </tbody></table></div>

        <div className={s.sectionTitle}>Compliance Retention Policy</div>
        <div className={s.sectionTitle}>Must Retain</div>
        {(auditTrail.retention_policy?.retain_mandatory || []).map((row: any, index: number) => <div key={index} className={s.kvRow}><span className={s.mono}>{row.field}</span><span title={row.reason}>{row.min_retention_days}d — {row.reason?.slice(0, 60)}</span></div>)}
        <div className={s.sectionTitle}>Purge Eligible</div>
        {(auditTrail.retention_policy?.purge_eligible || []).map((row: any, index: number) => <div key={index} className={s.kvRow}><span className={s.mono}>{row.field}</span><span>After {row.after_days}d — {row.reason?.slice(0, 60)}</span></div>)}
        {(auditTrail.retention_policy?.pii_fields_detected || []).length > 0 && <><div className={s.sectionTitle}>PII Fields Detected</div><div className={s.tagRow}>{auditTrail.retention_policy.pii_fields_detected.map((field: string) => <span key={field} className={s.tag}>{field}</span>)}</div></>}
      </>}
    </div>
  );
}
