import React, { useEffect, useState } from 'react';
import { fetchIncidents, type IncidentRow, updateIncidentStatus, fetchSecurityEventById } from '../api';

export function Incidents() {
  const [incidents, setIncidents] = useState<IncidentRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<any | null>(null);
  const [page, setPage] = useState(0);
  const [limit] = useState(20);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchIncidents({ limit, offset: page * limit, status: statusFilter || undefined, severity: severityFilter || undefined })
      .then((r) => { if (!cancelled) setIncidents(r); })
      .catch((e: any) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [page, limit, statusFilter, severityFilter]);

  function exportCsv() {
    const rows = incidents.map(i => ({ id: i.id, event_id: i.event_id, severity: i.severity, status: i.status, title: i.title }));
    const header = Object.keys(rows[0] || {}).join(',') + '\n';
    const body = rows.map(r => Object.values(r).map(v => '"'+String(v||'')+'"').join(',')).join('\n');
    const csv = header + body;
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `incidents_${Date.now()}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="card">
      <h3>Incidents</h3>
      {loading && <div className="page-sub">Loading...</div>}
      {error && <div className="page-sub" style={{ color: '#9f2d1b' }}>Error: {error}</div>}
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <select value={statusFilter||''} onChange={(e) => setStatusFilter(e.target.value||null)}>
          <option value="">All statuses</option>
          <option value="open">open</option>
          <option value="triaged">triaged</option>
          <option value="blocked">blocked</option>
          <option value="resolved">resolved</option>
        </select>
        <select value={severityFilter||''} onChange={(e) => setSeverityFilter(e.target.value||null)}>
          <option value="">All severities</option>
          <option value="critical">critical</option>
          <option value="high">high</option>
          <option value="warn">warn</option>
          <option value="info">info</option>
        </select>
        <button className="btn" onClick={exportCsv}>Export CSV</button>
      </div>
      <table className="table">
        <thead>
          <tr><th>ID</th><th>Event</th><th>Severity</th><th>Title</th><th>Status</th><th>Actions</th></tr>
        </thead>
        <tbody>
          {incidents.map(i => (
            <tr key={i.id}>
              <td>{i.id}</td>
              <td>
                {i.event_id ? (
                  <button className="link" onClick={async () => {
                    try {
                      const ev = await fetchSecurityEventById(i.event_id as string);
                      setSelectedEvent(ev);
                    } catch (e:any) { alert('Error: '+(e.message||e)); }
                  }}>{i.event_id}</button>
                ) : '—'}
              </td>
              <td>{i.severity}</td>
              <td style={{ maxWidth: 240 }}>{i.title}</td>
              <td>{i.status}</td>
              <td style={{ display: 'flex', gap: 6 }}>
                <button className="btn" onClick={async () => { try { await updateIncidentStatus(i.id, 'open'); alert('Updated'); } catch (e:any) { alert('Error: '+(e.message||e)); } }}>Open</button>
                <button className="btn" onClick={async () => { try { await updateIncidentStatus(i.id, 'triaged'); alert('Updated'); } catch (e:any) { alert('Error: '+(e.message||e)); } }}>Triaged</button>
                <button className="btn" onClick={async () => { try { await updateIncidentStatus(i.id, 'resolved'); alert('Updated'); } catch (e:any) { alert('Error: '+(e.message||e)); } }}>Resolve</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
        <div>
          <button className="btn" disabled={page<=0} onClick={() => setPage(p => Math.max(0, p-1))}>Prev</button>
          <button className="btn" style={{ marginLeft: 8 }} onClick={() => setPage(p => p+1)}>Next</button>
        </div>
        <div>Page {page+1}</div>
      </div>
      {selectedEvent && (
        <div className="modal-backdrop" onClick={() => setSelectedEvent(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 800 }}>
            <h3>Security Event {selectedEvent.id}</h3>
            <div>Severity: {selectedEvent.severity} — Path: {selectedEvent.path}</div>
            <div style={{ marginTop: 8 }}>
              <strong>Payload</strong>
              <pre style={{ maxHeight: 240, overflow: 'auto', background: '#f8fafc', padding: 8 }}>{JSON.stringify(selectedEvent.details?.payload, null, 2)}</pre>
            </div>
            <div style={{ marginTop: 8 }}>
              <strong>Analysis</strong>
              <pre style={{ maxHeight: 240, overflow: 'auto', background: '#f8fafc', padding: 8 }}>{JSON.stringify(selectedEvent.details?.analysis, null, 2)}</pre>
            </div>
            <div style={{ marginTop: 8 }}>
              <button className="btn" onClick={() => setSelectedEvent(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
