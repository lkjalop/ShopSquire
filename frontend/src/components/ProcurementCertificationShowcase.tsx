import { useCallback, useEffect, useState } from 'react';

import { apiRequestHeaders, apiUrl } from '../lib/api';
import styles from './ProcurementCertificationShowcase.module.css';

const words = (value: unknown) => String(value ?? 'unknown').replace(/_/g, ' ');

export default function ProcurementCertificationShowcase() {
  const [certificate, setCertificate] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    fetch(apiUrl('/api/v1/certification/procurement/conversational-spatiotemporal/evaluate'), {
      method: 'POST',
      credentials: 'include',
      headers: apiRequestHeaders({}, true),
      body: JSON.stringify({}),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`certificate_http_${response.status}`);
        return response.json();
      })
      .then(setCertificate)
      .catch((reason) => setError(String(reason?.message || reason)));
  }, []);
  useEffect(load, [load]);

  if (error) return <div className={styles.page}><div className={styles.error}>Certification unavailable: {error}</div></div>;
  if (!certificate) return <div className={styles.page}><div className={styles.shell}>Evaluating revisioned procurement case…</div></div>;

  const state = certificate.amended_state;
  const temporal = state.temporal;
  const allocation = certificate.allocation;
  const truth = certificate.canonical_truth;
  const allocatedPct = Math.round((allocation.allocated_units / allocation.requested_units) * 100);
  return (
    <main className={styles.page} data-testid="procurement-certification-showcase">
      <div className={styles.shell}>
        <div className={styles.eyebrow}>ShopSquire · Procurement Decision Lab</div>
        <h1 className={styles.title}>Language proposes. Deterministic state decides.</h1>
        <p className={styles.subtitle}>
          A two-turn, revision-bound procurement case with timezone authority, protected inventory,
          query-purpose separation, and no silent commercial action.
        </p>
        <div className={styles.badges}>
          <span className={styles.badge}>Certificate {certificate.passed ? 'passed' : 'failed'}</span>
          <span className={styles.badge}>Case revision {state.revision}</span>
          <span className={styles.badge}>Paid calls {certificate.provider_accounting.paid_calls}</span>
          <span className={styles.badge}>Commerce authority {truth.commerce_authority}</span>
          <span className={styles.badge}>Fixture clearly labelled</span>
        </div>

        <div className={styles.grid}>
          <section className={`${styles.card} ${styles.wide}`}>
            <h2>Buyer conversation retained as typed state</h2>
            <div className={styles.turn}><strong>Turn 1</strong><br />{certificate.turns[0]}</div>
            <div className={styles.turn}><strong>Turn 2</strong><br />{certificate.turns[1]}</div>
          </section>
          <section className={styles.card}>
            <h2>Atomic amendment</h2>
            <div className={styles.metricGrid} style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
              {state.destinations.map((row: any) => (
                <div className={styles.metric} key={row.location_ref}>
                  <span>{row.location_ref}</span><strong>{row.quantity} units</strong>
                </div>
              ))}
              <div className={styles.metric}><span>Total</span><strong>{state.requested_quantity}</strong></div>
              <div className={styles.metric}><span>Budget</span><strong>AUD {(state.budget.amount_minor / 100).toLocaleString()}</strong></div>
            </div>
            <p className={styles.success}>Workloads, deadline, budget and cover policy preserved.</p>
          </section>

          <section className={styles.card}>
            <h2>Temporal authority</h2>
            <p><strong>{temporal.original_expression}</strong> → {new Date(temporal.resolved_utc_instant).toISOString()}</p>
            <p className={styles.muted}>Timezone {temporal.timezone}<br />Interpreted {temporal.interpretation_instant}<br />{temporal.calendar_version}</p>
            <p className={styles.success}>Status {words(temporal.resolution_status)} · confidence {temporal.resolution_confidence}</p>
          </section>
          <section className={`${styles.card} ${styles.wide}`}>
            <h2>Purpose-bounded queries</h2>
            <div className={styles.metricGrid}>
              <div className={styles.metric}><span>Workload terms</span><strong>{state.workloads.join(' · ')}</strong></div>
              <div className={styles.metric}><span>Workload locations</span><strong>Excluded</strong></div>
              <div className={styles.metric}><span>Logistics locations</span><strong>Sydney · Perth</strong></div>
              <div className={styles.metric}><span>Before consent</span><strong>0 calls</strong></div>
              <div className={styles.metric}><span>Paid calls</span><strong>0</strong></div>
            </div>
          </section>

          <section className={`${styles.card} ${styles.wide}`}>
            <h2>Protected allocation and supplier shortfall</h2>
            <div className={styles.flow}>
              <strong>{allocation.allocated_units}/{allocation.requested_units}</strong>
              <div className={styles.bar}><span style={{ width: `${allocatedPct}%` }} /></div>
              <span>{allocatedPct}% by deadline</span>
            </div>
            <p>
              Minimum early arrival: <strong>30</strong> · protected origin cover: <strong>7 days</strong> ·
              supplier shortfall: <strong>{allocation.shortfall_units} units</strong>
            </p>
            <p className={styles.warning}>Supplier option is proposal-only. No RFQ was sent and no stock was reserved.</p>
          </section>
          <section className={styles.card}>
            <h2>Canonical truth</h2>
            <p>Research <strong>{words(truth.research_execution)}</strong></p>
            <p>Evidence <strong>{words(truth.evidence_status)}</strong></p>
            <p>Freshness <strong>{words(truth.freshness)}</strong></p>
            <p>Decision <strong>{words(truth.decision_status)}</strong></p>
            <p>Authority <strong>{words(truth.commerce_authority)}</strong></p>
          </section>

          <section className={`${styles.card} ${styles.full}`}>
            <h2>Sealed evidence</h2>
            <p className={styles.muted}>Deterministic fixture certificate · live-network certification is explicitly false.</p>
            <div className={styles.hash}>{certificate.artifact_sha256}</div>
          </section>
        </div>
      </div>
    </main>
  );
}
