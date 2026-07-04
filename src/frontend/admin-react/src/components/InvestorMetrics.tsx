import React, { useCallback, useEffect, useState } from 'react';
import { http } from '../api';

/**
 * Investor metrics (B1) — "show me the numbers" on ONE screen, composed server-side from aggregates that
 * already exist: exec KPIs, bounded-autonomy proof (allow vs governed-deny), market-governance pulse,
 * procurement cycle time, the capability-gap ledger, and fraud screening volume.
 * Each section degrades independently (a failed block renders its error note, never a blank screen).
 */

type Sections = Record<string, any>;

function Tile({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div style={{ border: '1px solid var(--border, #2a2f3a)', borderRadius: 10, padding: '12px 14px', minWidth: 170 }}>
      <div style={{ fontSize: 12, opacity: 0.7 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 2 }}>{value ?? '—'}</div>
      {hint && <div style={{ fontSize: 11, opacity: 0.55, marginTop: 2 }}>{hint}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ fontWeight: 700, margin: '10px 0 8px' }}>{title}</div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>{children}</div>
    </div>
  );
}

export function InvestorMetrics({ authVersion = 0, authReady = true }: { authVersion?: number; authReady?: boolean }) {
  const [data, setData] = useState<Sections | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);

  const load = useCallback(() => {
    setError(null);
    http<any>(`/api/v1/admin/bi/investor-metrics?days=${days}`)
      .then((d) => setData(d?.sections || {}))
      .catch((e) => setError(String(e?.message || e)));
  }, [days]);
  useEffect(() => { if (authReady) load(); }, [load, authVersion, authReady]);

  if (error) return <div className="error">investor-metrics unavailable: {error}</div>;
  if (!data) return <div>Loading…</div>;

  const ex = data.executive?.kpis || {};
  const au = data.autonomy || {};
  const pr = data.procurement || {};
  const cg = data.capability_gaps || {};
  const fr = data.fraud || {};
  const gv = data.governance || {};

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 12, opacity: 0.7 }}>Window</span>
        {[7, 30, 90].map((d) => (
          <button key={d} className={days === d ? 'active' : ''} onClick={() => setDays(d)}>{d}d</button>
        ))}
        <button onClick={load}>Refresh</button>
      </div>

      <Section title="Executive">
        <Tile label="Revenue" value={ex.revenue != null ? `$${Number(ex.revenue).toLocaleString()}` : '—'} />
        <Tile label="Gross margin" value={ex.gross_margin_pct != null ? `${ex.gross_margin_pct}%` : '—'} />
        <Tile label="Autonomy" value={ex.autonomy_pct != null ? `${ex.autonomy_pct}%` : '—'} hint="decisions auto vs human" />
        <Tile label="Refunds" value={ex.refund_pct != null ? `${ex.refund_pct}%` : '—'} />
      </Section>

      <Section title="Bounded autonomy — every action gated, allow AND deny audited">
        <Tile label="Storefront adaptations" value={au.market_adaptation?.allowed} hint="gate: ALLOW" />
        <Tile label="Governed denials" value={au.market_adaptation?.denied_governed} hint="refused to act on weak signals" />
        <Tile label="Supplier RFQs auto-sent" value={au.rfq?.sent} hint="autonomy OFF ⇒ 0 by design" />
        <Tile label="RFQ escalations" value={au.rfq?.escalated} hint="routed to a human" />
      </Section>

      <Section title="Procurement ops">
        <Tile label="Cases measured" value={pr.cases_measured} />
        <Tile label="Cycle time (median)" value={pr.cycle_hours_median != null ? `${pr.cycle_hours_median}h` : '—'} />
        <Tile label="Cycle time (p90)" value={pr.cycle_hours_p90 != null ? `${pr.cycle_hours_p90}h` : '—'} />
      </Section>

      <Section title="Fraud screening">
        <Tile label="Orders scored" value={fr.scored} hint="26+ signals per order" />
        <Tile label="High risk flagged" value={fr.high_risk} />
      </Section>

      <Section title="Capability-gap ledger — what buyers asked that we refused/couldn't do (roadmap feed)">
        {(cg.by_category || []).slice(0, 4).map((c: any) => (
          <Tile key={c.category} label={c.category} value={c.count} hint={`last: ${String(c.last_seen || '').slice(0, 16)}`} />
        ))}
        {!(cg.by_category || []).length && <Tile label="gaps recorded" value={0} />}
      </Section>

      <Section title="Market-intelligence governance pulse">
        {['signal_decision_state', 'experiment_health', 'policy_compliance', 'operational_pressure'].map((k) =>
          gv[k] ? (
            <div key={k} style={{ border: '1px solid var(--border, #2a2f3a)', borderRadius: 10, padding: '10px 12px', minWidth: 200, fontSize: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{k.replace(/_/g, ' ')}</div>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', opacity: 0.8 }}>{JSON.stringify(gv[k], null, 1).slice(1, -1).trim().slice(0, 300)}</pre>
            </div>
          ) : null,
        )}
      </Section>
    </div>
  );
}
