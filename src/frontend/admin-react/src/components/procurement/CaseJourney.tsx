/** Compact, bitemporal case and governed communication timeline. */
import React from 'react';
import type { CommunicationEvent, JourneyEvent } from '../../api';

export type UnifiedCaseActivity = {
  id: string;
  time: string;
  kind: 'case' | 'communication';
  label: string;
  state: string;
  actor: string;
  effect: 'changed' | 'prevented' | 'observed';
  reason?: string;
};

export function buildUnifiedCaseTimeline(
  journey: JourneyEvent[],
  communications: CommunicationEvent[],
): UnifiedCaseActivity[] {
  const caseEvents = journey.map((event, index): UnifiedCaseActivity => ({
    id: `case-${index}-${event.valid_from || ''}`,
    time: event.valid_from || '',
    kind: 'case',
    label: event.event,
    state: event.state,
    actor: event.actor_type,
    effect: event.reason_code?.includes('prevent') ? 'prevented' : 'changed',
    reason: event.reason_code,
  }));
  const messageEvents = communications.map((event): UnifiedCaseActivity => ({
    id: `message-${event.event_id}`,
    time: event.occurred_at || '',
    kind: 'communication',
    label: `message ${event.state}`,
    state: event.state,
    actor: event.actor_type,
    effect: event.commercial_effect === 'prevented' ? 'prevented' : 'observed',
    reason: event.reason,
  }));
  return [...caseEvents, ...messageEvents].sort((a, b) =>
    a.time.localeCompare(b.time) || a.id.localeCompare(b.id));
}

export function CaseJourney({
  journey,
  communications = [],
  communicationStatus = 'unavailable',
  asOfT,
  setAsOfT,
  asOf,
  onReconstruct,
  busy,
  onExportOkf,
}: {
  journey: JourneyEvent[];
  communications?: CommunicationEvent[];
  communicationStatus?: string;
  asOfT: string;
  setAsOfT: (value: string) => void;
  asOf: { as_of: string; state: string } | null;
  onReconstruct: () => void;
  busy: boolean;
  onExportOkf?: () => void;
}) {
  const activity = buildUnifiedCaseTimeline(journey, communications);
  return (
    <>
      {onExportOkf && (
        <div style={{ margin: '4px 0' }}>
          <button
            disabled={busy}
            data-testid="op-export-okf"
            onClick={onExportOkf}
            title="Export this case and decision trace as an OKF audit artifact"
          >
            Export OKF (audit artifact)
          </button>
        </div>
      )}
      <details data-testid="op-asof">
        <summary>Time-travel (as-of)</summary>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', margin: '4px 0' }}>
          <input
            value={asOfT}
            onChange={(event) => setAsOfT(event.target.value)}
            data-testid="op-asof-input"
            placeholder="2026-06-26 09:05:15"
            style={{ minWidth: 200 }}
          />
          <button disabled={busy || !asOfT} data-testid="op-asof-btn" onClick={onReconstruct}>
            Reconstruct
          </button>
          {asOf && (
            <span data-testid="op-asof-result">
              state at {asOf.as_of}: <strong>{asOf.state}</strong>
            </span>
          )}
        </div>
        <small style={{ color: '#6b7280' }}>
          The bitemporal record: the case exactly as it was at that instant.
        </small>
      </details>

      <details open data-testid="op-journey">
        <summary>Unified case and communication timeline ({activity.length})</summary>
        <div style={{ color: '#64748b', fontSize: 12, margin: '5px 0' }}>
          Case transitions and governed buyer/supplier messages, ordered by recorded time.
          Communication projection: {communicationStatus.replace(/_/g, ' ')}.
        </div>
        <ol data-testid="op-unified-timeline" style={{ paddingLeft: 22 }}>
          {activity.map((event) => (
            <li key={event.id} style={{ marginBottom: 6 }}>
              <span className="badge">{event.kind}</span>{' '}
              <strong>{event.label.replace(/_/g, ' ')}</strong>{' '}
              <span style={{ color: event.effect === 'prevented' ? '#991b1b' : '#475569' }}>
                {event.effect === 'prevented'
                  ? 'state prevented'
                  : event.effect === 'changed' ? 'state changed' : 'recorded'}
              </span>
              {' '}by {event.actor || 'system'}
              {event.reason ? ` — ${event.reason.replace(/_/g, ' ')}` : ''}
              {event.time && <small style={{ marginLeft: 6 }}>{event.time}</small>}
            </li>
          ))}
        </ol>
        {activity.length === 0 && <div>No recorded case or communication activity.</div>}
      </details>
    </>
  );
}

export default CaseJourney;
