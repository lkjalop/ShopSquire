/**
 * MarketIntelligence — operator view of the SYNTHETIC market replay.
 *
 * The replay drives the REAL market-intelligence path (market_signal → analyze → market_finding) with a
 * deterministic compressed 7-day curve, so advancing days shows demand spiking while conversion drops
 * and findings appear. Clearly labelled SYNTHETIC REPLAY — the ingestion/analysis/finding path is real;
 * only the events are synthetic, and they're written under an isolated demo tenant.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  experimentEvaluate, experimentPromote, experimentRevert, experimentState,
  fetchExecutiveMetrics,
  governancePulse, marketDigest, marketState, refreshMarket, replayAdvance, replayReset, replayState,
  supportResponse,
  type ExperimentState, type GovernancePulse, type MarketDigest, type ReplayState, type SupportResponse,
  type ExecutiveMetricProjection,
} from '../api';

const SEV_COLOR: Record<string, string> = { critical: 'crimson', warn: 'darkorange', info: 'gray' };

// authVersion bumps whenever the API key/cookie is (re)established — every fetch effect depends on it so the
// panel retries after auth succeeds. authReady gates the fetches so an UN-authed mount shows a clean
// "set your API key" placeholder instead of firing a burst of 401s and rendering empty cards.
export function MarketIntelligence({ authVersion = 0, authReady = true }:
                                   { authVersion?: number; authReady?: boolean } = {}) {
  const [st, setSt] = useState<ReplayState | null>(null);
  const [day, setDay] = useState(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executiveMetrics, setExecutiveMetrics] = useState<ExecutiveMetricProjection | null>(null);

  const [mode, setMode] = useState<'replay' | 'live'>('replay');

  const load = useCallback(() => {
    const fn = mode === 'live' ? marketState : replayState;
    fn().then(setSt).catch((e) => setError(e.message));
  }, [mode]);
  useEffect(() => { if (authReady) load(); }, [load, authVersion, authReady]);
  useEffect(() => {
    if (authReady) {
      fetchExecutiveMetrics().then(setExecutiveMetrics).catch(() => setExecutiveMetrics(null));
    }
  }, [authVersion, authReady, st]);

  const refreshLive = async () => {
    setBusy(true); setError(null);
    try {
      const r = await refreshMarket();
      setMode('live');
      // prefer the freshly-computed state from the pipeline run; fall back to a state read.
      setSt(r?.state ?? (await marketState()));
    } catch (e: any) { setError(e?.message || 'live refresh failed'); }
    finally { setBusy(false); }
  };
  // switch the VIEW between the synthetic replay and the live pipeline without re-running anything;
  // the load effect fetches the right endpoint for the new mode.
  const switchMode = (m: 'replay' | 'live') => { if (m !== mode) { setSt(null); setMode(m); } };

  // ── ranking-experiment console (the live-adaptation levers) ──
  const [exp, setExp] = useState<ExperimentState | null>(null);
  const loadExp = useCallback(() => { experimentState().then(setExp).catch(() => {}); }, []);
  useEffect(() => { if (authReady) loadExp(); }, [loadExp, authVersion, authReady]);
  const runExp = async (fn: () => Promise<any>) => {
    setBusy(true); setError(null);
    try { await fn(); loadExp(); }
    catch (e: any) { setError(e?.message || 'experiment action failed'); }
    finally { setBusy(false); }
  };

  const run = async (fn: () => Promise<any>) => {
    setBusy(true); setError(null);
    try { await fn(); load(); }
    catch (e: any) { setError(e?.message || 'replay action failed'); }
    finally { setBusy(false); }
  };

  // ── governance pulse (Step-11 owner visibility) — read-only; follows the active view's tenant so the
  //    figures match the findings panel above (synthetic replay writes the isolated 'replay-demo' tenant) ──
  const govTenant = mode === 'replay' ? 'replay-demo' : 'default';
  const [pulse, setPulse] = useState<GovernancePulse | null>(null);
  const [govNote, setGovNote] = useState<string | null>(null);
  const loadPulse = useCallback(() => {
    governancePulse(govTenant)
      .then((p) => { setPulse(p); setGovNote(null); })
      .catch(() => setGovNote('Governance visibility unavailable — check your API key / role (operator access required).'));
  }, [govTenant]);
  useEffect(() => { if (authReady) loadPulse(); }, [loadPulse, st, exp, authVersion, authReady]);

  // ── Market digest (deck M3 summarization) — on-demand operator brief. Deterministic facts; the
  //    flag-gated local-LLM only rewrites wording. Advisory-only: read-only projection, executes nothing. ──
  const [digest, setDigest] = useState<MarketDigest | null>(null);
  const [digestBusy, setDigestBusy] = useState(false);
  const loadDigest = async () => {
    setDigestBusy(true); setError(null);
    try { setDigest(await marketDigest()); }
    catch (e: any) { setError(e?.message || 'digest failed'); }
    finally { setDigestBusy(false); }
  };

  // ── M5 SUPPORT lane — the pre-sales angle to counter the dominant buyer objection (price→value, etc.).
  //    Recommends an APPROVED angle from support_response_policy; no free-form copy. Refreshes with the
  //    findings so the angle tracks what buyers are actually objecting to. ──
  const [support, setSupport] = useState<SupportResponse | null>(null);
  const loadSupport = useCallback(() => {
    supportResponse().then(setSupport).catch(() => setSupport(null));
  }, []);
  useEffect(() => { if (authReady) loadSupport(); }, [loadSupport, st, authVersion, authReady]);

  const series = st?.series;
  const live = mode === 'live';
  // the displayed source is driven by the active MODE (not just the last payload's label), so the
  // switch is unmistakable even before the next fetch lands.
  const sourceLabel = live ? (st?.label || 'LIVE') : (st?.label || 'SYNTHETIC REPLAY');
  const dataThrough = series?.dates?.length ? series.dates[series.dates.length - 1] : null;
  const adaptationAuthority = !exp
    ? 'NOT REPORTED'
    : exp.live
      ? 'LIVE ADAPTATION'
      : 'SHADOW / NOT LIVE';

  // Clean empty state instead of empty cards + a burst of 401s when the panel is opened before auth lands.
  if (!authReady) {
    return (
      <div className="market-intelligence" data-testid="market-intelligence">
        <strong>Market Intelligence</strong>
        <p className="page-sub" data-testid="mi-auth-needed" style={{ color: '#6b7280', marginTop: 8 }}>
          Set your API key to load market intelligence — the panel loads automatically once you authenticate.
        </p>
      </div>
    );
  }
  return (
    <div className="market-intelligence" data-testid="market-intelligence">
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <strong>Market Intelligence</strong>
        {/* color-coded, mode-driven source chip — green LIVE vs amber SYNTHETIC REPLAY */}
        <span data-testid="mi-label" style={{
          background: live ? '#dcfce7' : '#fef3c7', color: live ? '#166534' : '#92400e',
          padding: '2px 8px', borderRadius: 4, fontWeight: 700,
        }}>● {sourceLabel}</span>

        {/* explicit view toggle: switch what you're looking at without re-running anything */}
        <span style={{ display: 'inline-flex', border: '1px solid #d1d5db', borderRadius: 6, overflow: 'hidden' }}>
          <button disabled={busy} data-testid="mi-mode-replay" onClick={() => switchMode('replay')}
                  style={{ border: 'none', padding: '3px 8px', cursor: 'pointer',
                           background: live ? '#fff' : '#fde68a', fontWeight: live ? 400 : 700 }}>Synthetic replay</button>
          <button disabled={busy} data-testid="mi-mode-live" onClick={() => switchMode('live')}
                  style={{ border: 'none', borderLeft: '1px solid #d1d5db', padding: '3px 8px', cursor: 'pointer',
                           background: live ? '#bbf7d0' : '#fff', fontWeight: live ? 700 : 400 }}>Live</button>
        </span>

        {/* replay-only controls — hidden in live mode so the two sources can't be silently mixed */}
        {!live && (
          <>
            <button disabled={busy} onClick={() => run(replayReset)} data-testid="mi-reset">Reset</button>
            <label>Advance to day{' '}
              <select value={day} onChange={(e) => setDay(Number(e.target.value))} data-testid="mi-day">
                {[1, 2, 3, 4, 5, 6, 7].map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <button disabled={busy} onClick={() => run(() => replayAdvance(day))} data-testid="mi-advance">Advance</button>
          </>
        )}
        <span style={{ borderLeft: '1px solid #ccc', height: 18, margin: '0 4px' }} />
        <button disabled={busy} onClick={refreshLive} data-testid="mi-refresh-live"
                title="Run the REAL pipeline on live data (default tenant), then show LIVE findings">
          {live ? 'Re-run live pipeline' : 'Refresh live data'}
        </button>
      </div>
      <div data-testid="mi-trust-labels" style={{
        display: 'flex', gap: 8, flexWrap: 'wrap', margin: '-4px 0 12px', fontSize: 12,
      }}>
        <span className="badge">
          Evidence: {live ? 'OPERATIONAL PIPELINE' : 'SYNTHETIC'}
        </span>
        <span className="badge">
          Adaptation authority: {adaptationAuthority}
        </span>
        <span className="badge">
          Freshness: {dataThrough ? `data through ${dataThrough}` : 'NOT REPORTED'}
        </span>
      </div>

      {error && <p role="alert" style={{ color: 'crimson' }}>{error}</p>}

      <section data-testid="executive-metric-evidence"
               style={{ borderTop: '1px solid #e5e7eb', borderBottom: '1px solid #e5e7eb', padding: '12px 0', marginBottom: 14 }}>
        <h4 style={{ margin: '0 0 8px' }}>Executive metrics</h4>
        <div style={{ color: '#6b7280', fontSize: 12, marginBottom: 8 }}>
          Tenant-scoped evidence. Estimated, simulated, insufficient and unavailable values are never presented as observed.
        </div>
        {!executiveMetrics ? (
          <div>Metric evidence unavailable.</div>
        ) : (
          <>
            <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginBottom: 8 }}>
              <span>Canonical events <strong>{executiveMetrics.data_quality.event_count ?? 0}</strong></span>
              <span>RFM customers <strong>{executiveMetrics.estimates.customer_estimate_count ?? 0}</strong> <small>(estimate)</small></span>
              <span>High churn <strong>{executiveMetrics.estimates.high_churn_estimate_count ?? 0}</strong> <small>(estimate)</small></span>
            </div>
            <table style={{ width: '100%' }}>
              <thead><tr><th>SKU</th><th>Metric</th><th>Value</th><th>Evidence status</th><th>As of</th><th>Evidence quality</th></tr></thead>
              <tbody>
                {executiveMetrics.metrics.slice(0, 30).map((metric, index) => (
                  <tr key={`${metric.subject_id}-${metric.metric}-${index}`}>
                    <td>{metric.subject_id}</td>
                    <td>{metric.metric.replace(/_/g, ' ')}</td>
                    <td>{metric.value == null ? 'Unavailable' : `${Number(metric.value).toFixed(2)} ${metric.unit || ''}`}</td>
                    <td>{metric.status.replace(/_/g, ' ')}</td>
                    <td>{new Date(metric.as_of).toLocaleString()}</td>
                    <td>
                      <details>
                        <summary>
                          {metric.source_count} source(s) · {(metric.coverage * 100).toFixed(0)}% coverage
                          {' · '}{(metric.confidence * 100).toFixed(0)}% confidence
                        </summary>
                        <div>Definition: {metric.definition_version}</div>
                        {metric.reason && <div>Reason: {metric.reason.replace(/_/g, ' ')}</div>}
                        {metric.provenance_chain.map((source) => <div key={source}><code>{source}</code></div>)}
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <div style={{ display: 'flex', gap: 24 }}>
        <div>
          <div>Signals: <strong data-testid="mi-signals">{st?.signals ?? 0}</strong></div>
          <div>Active findings: <strong data-testid="mi-findings-count">{st?.active_findings ?? 0}</strong></div>
        </div>
        {series && (
          <table>
            <thead><tr><th></th>{series.dates.map((d) => <th key={d}>{d.slice(5)}</th>)}</tr></thead>
            <tbody>
              <tr><td>Demand</td>{series.demand.map((v, i) => <td key={i}>{v}</td>)}</tr>
              <tr><td>Conversion</td>{series.conversion.map((v, i) => <td key={i}>{v}</td>)}</tr>
            </tbody>
          </table>
        )}
      </div>

      <h4>Findings</h4>
      <ul data-testid="mi-findings">
        {(st?.findings || []).map((f, i) => (
          <li key={i}>
            <span style={{ color: SEV_COLOR[f.severity] || 'black', fontWeight: 600 }}>
              {f.severity.toUpperCase()}
            </span>{' '}
            <code>{f.type}</code>{f.entity_ref ? ` (${f.entity_ref})` : ''} — {f.summary}
          </li>
        ))}
        {(st?.findings || []).length === 0 && (
          <li><em>no active findings — {mode === 'live' ? 'refresh live data' : 'advance the replay'}</em></li>
        )}
      </ul>

      {/* Market digest (deck M3 summarization): the operator's brief. Deterministic facts always; the
          flag-gated local-LLM only rewrites the narrative wording. Advisory-only — executes nothing. */}
      <section data-testid="mi-digest" style={{ marginTop: 16, borderTop: '1px solid #eee', paddingTop: 12 }}>
        <h4 style={{ margin: '0 0 6px' }}>Market digest (operator brief)</h4>
        <button disabled={digestBusy || busy} onClick={loadDigest} data-testid="mi-digest-generate">
          {digestBusy ? 'Generating…' : (digest ? 'Regenerate digest' : 'Generate digest')}
        </button>
        {digest && (
          <div style={{ marginTop: 8 }}>
            <div style={{ background: '#eef2ff', border: '1px solid #c7d2fe', borderRadius: 8, padding: '10px 12px' }}>
              <div data-testid="mi-digest-narrative">{digest.narrative}</div>
              <div style={{ marginTop: 6, fontSize: 12, color: '#6b7280' }}>
                {digest.finding_count} finding(s) · {Object.entries(digest.by_severity).map(([s, n]) => `${n} ${s}`).join(' · ') || 'none'}
                {' · '}
                {digest.mode === 'llm_rewrite'
                  ? 'narrative wording by local LLM — facts deterministic'
                  : 'fully deterministic (no LLM)'}
                {' · advisory only — nothing executes from this brief'}
              </div>
            </div>
            {digest.suggested_focus.length > 0 && (
              <ul data-testid="mi-digest-focus" style={{ marginTop: 8 }}>
                {digest.suggested_focus.map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            )}
          </div>
        )}
      </section>

      {/* Live-adaptation console: arm/observe/evaluate/revert the reversible ranking experiment.
          Arming only flips status — the nudge still needs RANKING_NUDGE_EXPERIMENT_ENABLED to fire. */}
      <section data-testid="mi-experiment" style={{ marginTop: 16, borderTop: '1px solid #eee', paddingTop: 12 }}>
        <h4 style={{ margin: '0 0 6px' }}>Ranking experiment (live adaptation)</h4>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span data-testid="exp-status" style={{
            background: exp?.live ? '#dcfce7' : '#f3f4f6', color: exp?.live ? '#166534' : '#374151',
            padding: '2px 8px', borderRadius: 4, fontWeight: 700,
          }}>
            {exp?.live ? 'LIVE' : (exp?.status || 'absent').toUpperCase()}
          </span>
          {exp && (
            <small>control {exp.assignments?.control || 0} · treatment {exp.assignments?.treatment || 0}
              {exp.last_decision ? ` · last: ${exp.last_decision} (${exp.last_uplift_pct ?? '–'}%)` : ''}
              {exp.adaptation_killed ? ' · KILL-SWITCH ON' : ''}</small>
          )}
          <button disabled={busy} onClick={() => runExp(experimentPromote)} data-testid="exp-promote">Promote → live</button>
          <button disabled={busy} onClick={() => runExp(() => experimentEvaluate())} data-testid="exp-evaluate">Evaluate now</button>
          <button disabled={busy} onClick={() => runExp(experimentRevert)} data-testid="exp-revert"
                  style={{ color: 'crimson' }}>Revert (kill)</button>
        </div>
        <small style={{ color: '#6b7280' }}>
          Arming flips status only; the nudge fires for TREATMENT users behind the confidence/authz gate
          when RANKING_NUDGE_EXPERIMENT_ENABLED is on. Evaluate runs uplift → decide → auto-revert on no-lift.
        </small>
      </section>

      {/* Governance visibility (deck Step 11): the owner OBSERVES the autonomous subsystem without becoming a
          runtime dependency. Read-only roll-up of the existing audit trails into four cards. */}
      {pulse && (
        <section data-testid="mi-governance" style={{ marginTop: 16, borderTop: '1px solid #eee', paddingTop: 12 }}>
          <h4 style={{ margin: '0 0 8px' }}>Governance visibility{' '}
            <span data-testid="gov-tenant" style={{ fontWeight: 400, fontSize: 12, color: '#6b7280' }}>
              (tenant: {pulse.tenant_id})</span></h4>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <GovCard title="Signal & decision state" testid="gov-signal">
              <Row k="Active findings" v={pulse.signal_decision_state.active_findings} />
              <Row k="Critical / warn / info"
                   v={`${sev(pulse, 'critical')} / ${sev(pulse, 'warn')} / ${sev(pulse, 'info')}`} />
              <Row k="AI confidence (lo/med/hi)"
                   v={`${conf(pulse, 'low')} / ${conf(pulse, 'medium')} / ${conf(pulse, 'high')}`} />
              <Row k="Adaptation mode"
                   v={`${pulse.signal_decision_state.adaptation_mode.kill_switch ? 'KILLED' : 'armed'} · hippograph=${pulse.signal_decision_state.adaptation_mode.hippograph_mode}`} />
            </GovCard>

            <GovCard title={`Experiment health${pulse.experiment_health.scope === 'global' ? ' (global)' : ''}`}
                     testid="gov-experiment">
              <Row k="Status" v={pulse.experiment_health.live ? 'LIVE' : pulse.experiment_health.status} />
              <Row k="Outcomes recorded" v={pulse.experiment_health.outcomes_recorded} />
              <Row k="Rollback count" v={pulse.experiment_health.rollback_count}
                   warn={pulse.experiment_health.rollback_count > 0} />
              <Row k="Last decision"
                   v={`${pulse.experiment_health.last_decision ?? '–'} (${pulse.experiment_health.last_uplift_pct ?? '–'}%)`} />
            </GovCard>

            <GovCard title="Policy & compliance" testid="gov-policy">
              <Row k="Policy block rate"
                   v={`${(pulse.policy_compliance.policy_block_rate * 100).toFixed(1)}% (${pulse.policy_compliance.actions_blocked}/${pulse.policy_compliance.actions_evaluated})`}
                   warn={pulse.policy_compliance.policy_block_rate > 0.25} />
              <Row k="Contacts suppressed"
                   v={`${pulse.policy_compliance.contacts_suppressed}/${pulse.policy_compliance.contacts_evaluated}`} />
              <Row k="Suppression by region"
                   v={kvStr(pulse.policy_compliance.suppression_by_region) || '–'} />
              <Row k="Exception count" v={pulse.policy_compliance.exception_count}
                   warn={pulse.policy_compliance.exception_count > 0} />
            </GovCard>

            <GovCard title="Operational pressure" testid="gov-pressure">
              <Row k="Critical findings" v={pulse.operational_pressure.critical_findings}
                   warn={pulse.operational_pressure.critical_findings > 0} />
              <Row k="Open action proposals" v={pulse.operational_pressure.open_action_proposals} />
              <Row k="Findings by type"
                   v={kvStr(pulse.operational_pressure.findings_by_type) || '–'} />
            </GovCard>
          </div>
          <small style={{ color: '#6b7280' }}>
            Read-only — the owner observes without becoming a runtime dependency. Every figure is rolled up
            from the durable audit trails (adaptive-action gate, contact governance, experiment outcomes, findings).
          </small>
        </section>
      )}
      {!pulse && govNote && (
        <section data-testid="mi-governance-note" style={{ marginTop: 16, borderTop: '1px solid #eee', paddingTop: 12 }}>
          <h4 style={{ margin: '0 0 6px' }}>Governance visibility</h4>
          <p role="alert" style={{ color: 'crimson', margin: 0 }}>{govNote}</p>
        </section>
      )}

      {/* M5 SUPPORT lane — the pre-sales objection-handling angle, made visible. The angle is chosen by
          policy from the dominant buyer objection; the support runtime renders APPROVED copy for it. */}
      {support && support.response_angle && (
        <section data-testid="mi-support" style={{ marginTop: 16, borderTop: '1px solid #eee', paddingTop: 12 }}>
          <h4 style={{ margin: '0 0 8px' }}>Support response lane{' '}
            <span style={{ fontWeight: 400, fontSize: 12, color: '#6b7280' }}>
              (objection handling · {support.source === 'explicit' ? 'explicit' : 'dominant objection'})</span></h4>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <GovCard title="Recommended angle" testid="support-angle">
              <Row k="Objection theme" v={support.objection_theme || '–'} />
              <Row k="Response angle" v={<strong style={{ color: '#166534' }}>{support.response_angle}</strong>} />
            </GovCard>
            {support.guidance && (
              <GovCard title="Guidance" testid="support-guidance">
                <div style={{ fontSize: 13, color: '#374151' }}>{support.guidance}</div>
              </GovCard>
            )}
          </div>
          <small style={{ color: '#6b7280' }}>
            Recommends only — the support runtime renders approved copy for this angle; it never free-forms a reply.
          </small>
        </section>
      )}
    </div>
  );
}

const sev = (p: GovernancePulse, k: string) => p.signal_decision_state.findings_by_severity[k] || 0;
const conf = (p: GovernancePulse, k: string) => p.signal_decision_state.ai_confidence_distribution[k] || 0;
const kvStr = (m: Record<string, number>) =>
  Object.entries(m || {}).map(([k, v]) => `${k}:${v}`).join(', ');

function GovCard({ title, testid, children }: { title: string; testid: string; children: React.ReactNode }) {
  return (
    <div data-testid={testid} style={{
      border: '1px solid #e5e7eb', borderRadius: 8, padding: 12, minWidth: 240, flex: '1 1 240px',
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  );
}

function Row({ k, v, warn }: { k: string; v: React.ReactNode; warn?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, padding: '1px 0' }}>
      <span style={{ color: '#6b7280' }}>{k}</span>
      <strong style={{ color: warn ? 'crimson' : '#111827' }}>{v}</strong>
    </div>
  );
}

export default MarketIntelligence;
