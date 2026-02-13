import React, { useEffect, useState } from 'react';
import { fetchInventoryConnectorSummary, fetchInventoryExternalStock, fetchInventorySyncRuns, runInventorySync } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

export function InventorySync({ role }: Props) {
  const [summary, setSummary] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [snapshot, setSnapshot] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');
  const [connectorId, setConnectorId] = useState('csv');

  async function refresh() {
    const [c, r, s] = await Promise.all([fetchInventoryConnectorSummary(5), fetchInventorySyncRuns(50), fetchInventoryExternalStock(80)]);
    setSummary(c.items || []);
    setRuns(r.items || []);
    setSnapshot(s.items || []);
  }

  useEffect(() => {
    refresh().catch(() => {});
  }, []);

  const locked = !(role === 'owner' || role === 'developer');

  return (
    <div className="stagger">
      <div className="card">
        <h3>Inventory Sync</h3>
        <div className="page-sub" style={{ marginTop: 6 }}>
          Phase 5 MVP: ingest external inventory snapshots (CSV first) into `inventory_external_stock` and log runs.
        </div>
        {locked && (
          <div className="callout" style={{ marginTop: 12 }}>
            Locked: Owner/Developer only.
          </div>
        )}
      </div>

      <div className="card">
        <h4 style={{ marginTop: 0 }}>Connectors</h4>
        <div className="grid-2" style={{ marginTop: 10 }}>
          {(summary || []).map((c) => (
            <div key={c.id} className="card" style={{ padding: 14, overflow: 'hidden' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <div style={{ fontWeight: 700 }}>{c.name}</div>
                <div className={`pill ${c.health?.ok ? '' : 'danger'}`}>{c.health?.ok ? 'Healthy' : 'Unhealthy'}</div>
              </div>
              <div className="page-sub" style={{ marginTop: 6 }}>
                {c.last_run?.started_at ? (
                  <>Last sync: <span className="mono">{c.last_run.started_at}</span> • status: <span className="mono">{c.last_run.status}</span> • changed: <span className="mono">{c.delta_applied ?? c.last_run.records_applied ?? 0}</span></>
                ) : (
                  <>No sync runs yet.</>
                )}
              </div>
              <pre style={{ marginTop: 10, whiteSpace: 'pre-wrap' }}>{JSON.stringify(c.health || {}, null, 2)}</pre>
              {!!(c.sample || []).length && (
                <>
                  <div className="page-sub" style={{ marginTop: 10 }}>Sample rows</div>
                  <div className="table" style={{ marginTop: 8 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>SKU</th>
                          <th>WH</th>
                          <th>Stock</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(c.sample || []).slice(0, 5).map((r: any, idx: number) => (
                          <tr key={`${c.id}-${idx}`}>
                            <td className="mono">{r.sku}</td>
                            <td className="mono">{r.warehouse}</td>
                            <td className="mono">{r.stock}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <select value={connectorId} onChange={(e) => setConnectorId(e.target.value)} className="role-select" disabled={locked || loading}>
            {(summary || []).map((c) => (
              <option key={c.id} value={c.id}>{c.id}</option>
            ))}
          </select>
          <button className="btn secondary" onClick={() => refresh().catch(() => {})}>Refresh</button>
          <button
            className="btn"
            disabled={locked || loading}
            onClick={async () => {
              setLoading(true);
              setMsg('');
              try {
                const out = await runInventorySync({ connector: connectorId, dry_run: false, upsert_products: false });
                setMsg(`Sync: ${out.status} (seen=${out.records_seen} applied=${out.records_applied})`);
                await refresh();
              } catch (e: any) {
                setMsg(e?.message || 'sync failed');
              } finally {
                setLoading(false);
              }
            }}
          >
            Run CSV Sync
          </button>
          {msg && <div className="pill">{msg}</div>}
        </div>
      </div>

      <div className="card">
        <h4 style={{ marginTop: 0 }}>Recent Runs</h4>
        <div className="table">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Source</th>
                <th>Status</th>
                <th>Seen</th>
                <th>Applied</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {(runs || []).slice(0, 20).map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.started_at || ''}</td>
                  <td>{r.source}</td>
                  <td>{r.status}</td>
                  <td className="mono">{r.records_seen ?? ''}</td>
                  <td className="mono">{r.records_applied ?? ''}</td>
                  <td className="mono">{r.error || ''}</td>
                </tr>
              ))}
              {(!runs || runs.length === 0) && (
                <tr>
                  <td colSpan={6} className="page-sub">No runs yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h4 style={{ marginTop: 0 }}>Recent External Snapshot Rows</h4>
        <div className="table">
          <table>
            <thead>
              <tr>
                <th>Observed</th>
                <th>Source</th>
                <th>SKU</th>
                <th>Warehouse</th>
                <th>Stock</th>
              </tr>
            </thead>
            <tbody>
              {(snapshot || []).slice(0, 30).map((it) => (
                <tr key={it.id}>
                  <td className="mono">{it.observed_at || ''}</td>
                  <td>{it.source}</td>
                  <td className="mono">{it.sku}</td>
                  <td className="mono">{it.warehouse}</td>
                  <td className="mono">{it.stock}</td>
                </tr>
              ))}
              {(!snapshot || snapshot.length === 0) && (
                <tr>
                  <td colSpan={5} className="page-sub">No snapshot rows yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="page-sub" style={{ marginTop: 10 }}>
          For BI/PowerBI, use the CSV endpoints under Admin → Compliance/Exports or query these tables directly in Postgres.
        </div>
      </div>
    </div>
  );
}
