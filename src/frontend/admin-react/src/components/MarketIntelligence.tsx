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
  marketState, refreshMarket, replayAdvance, replayReset, replayState,
  type ExperimentState, type ReplayState,
} from '../api';

const SEV_COLOR: Record<string, string> = { critical: 'crimson', warn: 'darkorange', info: 'gray' };

export function MarketIntelligence() {
  const [st, setSt] = useState<ReplayState | null>(null);
  const [day, setDay] = useState(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [mode, setMode] = useState<'replay' | 'live'>('replay');

  const load = useCallback(() => {
    const fn = mode === 'live' ? marketState : replayState;
    fn().then(setSt).catch((e) => setError(e.message));
  }, [mode]);
  useEffect(() => { load(); }, [load]);

  const refreshLive = async () => {
    setBusy(true); setError(null);
    try { const r = await refreshMarket(); setMode('live'); setSt(r.state); }
    catch (e: any) { setError(e?.message || 'live refresh failed'); }
    finally { setBusy(false); }
  };

  // ── ranking-experiment console (the live-adaptation levers) ──
  const [exp, setExp] = useState<ExperimentState | null>(null);
  const loadExp = useCallback(() => { experimentState().then(setExp).catch(() => {}); }, []);
  useEffect(() => { loadExp(); }, [loadExp]);
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

  const series = st?.series;
  return (
    <div className="market-intelligence" data-testid="market-intelligence">
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <strong>Market Intelligence</strong>
        <span style={{ background: '#eee', padding: '2px 6px', borderRadius: 4 }} data-testid="mi-label">
          {st?.label || 'SYNTHETIC REPLAY'}
        </span>
        <button disabled={busy} onClick={() => run(replayReset)} data-testid="mi-reset">Reset</button>
        <label>Advance to day{' '}
          <select value={day} onChange={(e) => setDay(Number(e.target.value))} data-testid="mi-day">
            {[1, 2, 3, 4, 5, 6, 7].map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <button disabled={busy} onClick={() => run(() => replayAdvance(day))} data-testid="mi-advance">Advance</button>
        <span style={{ borderLeft: '1px solid #ccc', height: 18, margin: '0 4px' }} />
        <button disabled={busy} onClick={refreshLive} data-testid="mi-refresh-live"
                title="Run the REAL pipeline on live data (default tenant)">Refresh live data</button>
      </div>

      {error && <p role="alert" style={{ color: 'crimson' }}>{error}</p>}

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
          <button disabled={busy} onClick={() => runExp(() => experimentEvaluate(1))} data-testid="exp-evaluate">Evaluate now</button>
          <button disabled={busy} onClick={() => runExp(experimentRevert)} data-testid="exp-revert"
                  style={{ color: 'crimson' }}>Revert (kill)</button>
        </div>
        <small style={{ color: '#6b7280' }}>
          Arming flips status only; the nudge fires for TREATMENT users behind the confidence/authz gate
          when RANKING_NUDGE_EXPERIMENT_ENABLED is on. Evaluate runs uplift → decide → auto-revert on no-lift.
        </small>
      </section>
    </div>
  );
}

export default MarketIntelligence;
