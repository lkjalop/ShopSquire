/**
 * MarketIntelligence — operator view of the SYNTHETIC market replay.
 *
 * The replay drives the REAL market-intelligence path (market_signal → analyze → market_finding) with a
 * deterministic compressed 7-day curve, so advancing days shows demand spiking while conversion drops
 * and findings appear. Clearly labelled SYNTHETIC REPLAY — the ingestion/analysis/finding path is real;
 * only the events are synthetic, and they're written under an isolated demo tenant.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { replayAdvance, replayReset, replayState, type ReplayState } from '../api';

const SEV_COLOR: Record<string, string> = { critical: 'crimson', warn: 'darkorange', info: 'gray' };

export function MarketIntelligence() {
  const [st, setSt] = useState<ReplayState | null>(null);
  const [day, setDay] = useState(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    replayState().then(setSt).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

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
        {(st?.findings || []).length === 0 && <li><em>no active findings — advance the replay</em></li>}
      </ul>
    </div>
  );
}

export default MarketIntelligence;
