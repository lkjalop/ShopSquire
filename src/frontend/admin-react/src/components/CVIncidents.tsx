import React, { useEffect, useMemo, useState } from 'react';
import { fetchCVIncidentsBySku, fetchCVIncidentsRecent } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

export function CVIncidents({ role }: Props) {
  const [recent, setRecent] = useState<any[]>([]);
  const [bySku, setBySku] = useState<any[]>([]);
  const [selectedSku, setSelectedSku] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchCVIncidentsRecent(80), fetchCVIncidentsBySku(500)])
      .then(([r, s]) => {
        setRecent(r.items || []);
        setBySku(s.items || []);
      })
      .catch(() => {});
  }, []);

  const filtered = useMemo(() => {
    if (!selectedSku) return recent;
    return (recent || []).filter((it) => String(it.sku || '') === selectedSku);
  }, [recent, selectedSku]);

  return (
    <div className="stagger">
      <div className="card">
        <h3>CV Incidents</h3>
        <div className="page-sub" style={{ marginTop: 6 }}>
          Derived from persisted `evidence_bundles` so it works in SQLite and Postgres without extra schema.
        </div>
      </div>

      <div className="card">
        <h4 style={{ marginTop: 0 }}>By SKU</h4>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
          <button className={`btn secondary ${!selectedSku ? 'active' : ''}`} onClick={() => setSelectedSku(null)}>
            All
          </button>
          {(bySku || []).slice(0, 20).map((row) => (
            <button
              key={row.sku}
              className={`btn secondary ${selectedSku === row.sku ? 'active' : ''}`}
              onClick={() => setSelectedSku(row.sku)}
              title={`packs: ${(row.pack_ids || []).join(', ')}`}
            >
              {row.sku} ({row.count})
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <h4 style={{ marginTop: 0 }}>Recent Evidence</h4>
        <div className="table">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>SKU</th>
                <th>Pack</th>
                <th>Order</th>
                <th>Serial</th>
                <th>Tags</th>
                <th>Manip</th>
              </tr>
            </thead>
            <tbody>
              {(filtered || []).slice(0, 50).map((it) => (
                <tr key={it.evidence_id}>
                  <td className="mono">{it.created_at || ''}</td>
                  <td className="mono">{it.sku || ''}</td>
                  <td className="mono">{it.pack_id || ''}</td>
                  <td className="mono">{it.cv_fields?.order_id || ''}</td>
                  <td className="mono">{it.cv_fields?.serial || ''}</td>
                  <td className="mono">{(it.evidence_tags || []).slice(0, 4).join(', ')}</td>
                  <td className="mono">{it.manipulation_score ?? ''}</td>
                </tr>
              ))}
              {(!filtered || filtered.length === 0) && (
                <tr>
                  <td colSpan={7} className="page-sub">No CV incidents found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="page-sub" style={{ marginTop: 10 }}>
          Next hardening step: persist Tier2 forensics summary explicitly for drift dashboards (optional).
        </div>
      </div>
    </div>
  );
}

