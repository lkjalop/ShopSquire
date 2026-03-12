import React from 'react'

import { useEffect, useState } from 'react';
import EscalationRoom from './components/EscalationRoom';
import { apiUrl, safeJson } from './lib/api';

export default function AdminShell() {
  const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';
  const OWNER_API_KEY = ((import.meta as any).env?.VITE_OWNER_API_KEY as string | undefined) || API_KEY;
  const [incidentId, setIncidentId] = useState('');
  const [staffToken, setStaffToken] = useState(null);
  const [roomOpen, setRoomOpen] = useState(false);
  const [statusSummary, setStatusSummary] = useState(null);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [incidentsOpen, setIncidentsOpen] = useState(false);

  const fetchStatusSummary = async () => {
    try {
      const r = await fetch(apiUrl('/status/summary'));
      const j = await safeJson(r);
      setStatusSummary(j);
    } catch {
      setStatusSummary(null);
    }
  };

  useEffect(() => { fetchStatusSummary(); }, []);

  const fetchIncidents = async () => {
    try {
      const r = await fetch(apiUrl('/api/v1/admin/incidents/'), {
        credentials: 'include',
        headers: OWNER_API_KEY ? { 'x-api-key': OWNER_API_KEY } : undefined,
      });
      const j = await safeJson(r);
      if (Array.isArray(j?.incidents)) setIncidents(j.incidents);
    } catch {
      setIncidents([]);
    }
  };

  const issueStaffTokenAndJoin = async () => {
    const id = (incidentId || '').trim();
    if (!id) return;
    try {
      const r = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(id)}/room/token`), {
        method: 'POST',
        credentials: 'include',
        headers: OWNER_API_KEY ? { 'x-api-key': OWNER_API_KEY } : undefined,
      });
      const j = await safeJson(r);
      if (j && j.staff_token) {
        setStaffToken(String(j.staff_token));
        setRoomOpen(true);
      }
    } catch {}
  };

  return (
    <div style={{fontFamily: 'Inter, system-ui, Arial'}}>
      <h1>ShopSquire Admin</h1>
      <p>Admin analytics and Grafana embeds will appear here.</p>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6}}>
        <a href={apiUrl('/status/summary')} target="_blank" rel="noreferrer" style={{textDecoration: 'none'}}>
          <strong>Status Summary</strong>
        </a>
        <span style={{color: '#6b7280'}}>
          {statusSummary ? (
            `email warnings: ${statusSummary?.email_xdr?.warnings ?? 0} · outbound anomalies: ${statusSummary?.outbound_anomalies ?? 0}`
          ) : 'loading…'}
        </span>
        <button onClick={fetchStatusSummary} style={{padding: '4px 8px'}}>Refresh</button>
        <span style={{marginLeft: 8}}>
          <button onClick={() => { setIncidentsOpen(v => !v); if (!incidentsOpen) fetchIncidents(); }} style={{padding: '4px 8px', background: '#eef2ff', border: '1px solid #c7d2fe'}}>Incidents {incidents.length > 0 ? `(${incidents.length})` : ''}</button>
        </span>
      </div>
      <div style={{display: 'flex', gap: 12}}>
        <iframe title="grafana" src="/admin/grafana_proxy/api/dashboards/uid/shopsquire-geo" style={{width: 800, height: 600, border: '1px solid #ddd'}}/>
        <div>
          <h2>Quick Links</h2>
          <ul>
            <li><a href="/api/v1/analytics/ragas/summary">RAGAS Summary</a></li>
            <li><a href="/api/v1/analytics/query_clusters/latest">Latest Clusters</a></li>
            <li><a href="/metrics">Metrics</a></li>
          </ul>
          <div style={{marginTop: 16}}>
            <h3>Join Escalation Room</h3>
            <div style={{display: 'flex', gap: 8, alignItems: 'center'}}>
              <input placeholder="Incident ID" value={incidentId} onChange={(e) => setIncidentId(e.target.value)} style={{padding: '6px 8px', border: '1px solid #ddd', borderRadius: 4}} />
              <button onClick={issueStaffTokenAndJoin} style={{padding: '6px 10px'}}>Issue Staff Token & Join</button>
            </div>
          </div>
            {incidentsOpen && (
              <div style={{marginTop: 16}}>
                <h3>Incidents</h3>
                <div style={{display: 'flex', flexDirection: 'column', gap: 6}}>
                  {incidents.length === 0 && <div style={{color: '#6b7280'}}>No incidents loaded.</div>}
                  {incidents.map((it: any) => (
                    <div key={it.incident_id} style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid #e5e7eb', borderRadius: 6, padding: '6px 8px'}}>
                      <div>
                        <div><strong>{it.incident_id}</strong></div>
                        <div style={{fontSize: 12, color: '#6b7280'}}>{it.created_at || ''}</div>
                      </div>
                      <div style={{display: 'flex', gap: 8}}>
                        <button onClick={() => setIncidentId(it.incident_id)} style={{padding: '4px 8px'}}>Select</button>
                        <button onClick={() => { setIncidentId(it.incident_id); issueStaffTokenAndJoin(); }} style={{padding: '4px 8px'}}>Join</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
        </div>
      </div>
      {roomOpen && incidentId && (
        <EscalationRoom
          incidentId={incidentId}
          staffToken={staffToken}
          onClose={() => setRoomOpen(false)}
          onResolve={() => { fetchIncidents(); fetchStatusSummary(); }}
        />
      )}
    </div>
  );
}
