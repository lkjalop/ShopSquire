/** CaseJourney — the bitemporal time-travel (as-of) reader + the transition journey (extracted from
 *  ProcurementCases). Presentational; the as-of fetch is the parent's callback. */
import React from 'react';
import type { JourneyEvent } from '../../api';

export function CaseJourney({ journey, asOfT, setAsOfT, asOf, onReconstruct, busy, onExportOkf }: {
  journey: JourneyEvent[];
  asOfT: string;
  setAsOfT: (v: string) => void;
  asOf: { as_of: string; state: string } | null;
  onReconstruct: () => void;
  busy: boolean;
  onExportOkf?: () => void;
}) {
  return (
    <>
      {onExportOkf && (
        <div style={{ margin: '4px 0' }}>
          <button disabled={busy} data-testid="op-export-okf" onClick={onExportOkf}
                  title="Export this case + decision trace as an OKF (Open Knowledge Format) audit artifact">
            Export OKF (audit artifact)
          </button>
        </div>
      )}
      <details data-testid="op-asof">
        <summary>Time-travel (as-of)</summary>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', margin: '4px 0' }}>
          <input value={asOfT} onChange={(e) => setAsOfT(e.target.value)} data-testid="op-asof-input"
                 placeholder="2026-06-26 09:05:15" style={{ minWidth: 200 }} />
          <button disabled={busy || !asOfT} data-testid="op-asof-btn" onClick={onReconstruct}>Reconstruct</button>
          {asOf && <span data-testid="op-asof-result">state at {asOf.as_of}: <strong>{asOf.state}</strong></span>}
        </div>
        <small style={{ color: '#6b7280' }}>the bitemporal record — the case exactly as it was at that instant</small>
      </details>

      <details open data-testid="op-journey">
        <summary>Journey ({journey.length})</summary>
        <ol>
          {journey.map((e, i) => (
            <li key={i}>
              <code>{e.event}</code> → <strong>{e.state}</strong> by {e.actor_type}
              {e.reason_code ? ` (${e.reason_code})` : ''} <small>{e.valid_from}</small>
            </li>
          ))}
        </ol>
      </details>
    </>
  );
}

export default CaseJourney;
