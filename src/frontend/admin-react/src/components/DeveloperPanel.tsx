import React, { useEffect, useState } from 'react';
import { fetchMe, fetchToolInvocations, fetchDbReadiness, ensureTimescale, fetchCVReadiness, fetchTenantConfig, putTenantConfig, setApiKeyCookie, clearApiKeyCookie, setClientApiKey, fetchPreferences } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

export function DeveloperPanel({ role }: Props) {
  if (role !== 'developer') {
    return (
      <div className="callout">
        Developer-only space. Switch role to Developer to access keys, webhooks, and sandbox tooling.
      </div>
    );
  }

  const [keyInput, setKeyInput] = useState('');
  const [status, setStatus] = useState('');
  const [tools, setTools] = useState<any[]>([]);
  const [toolError, setToolError] = useState('');
  const [showPrefs, setShowPrefs] = useState(false);
  const [prefs, setPrefs] = useState<any | null>(null);
  const [dbReady, setDbReady] = useState<{ engine?: string; dialect?: string; connected?: boolean; migrations_ok?: boolean; timescale_ready?: boolean; error?: string | null } | null>(null);
  const [dbStatus, setDbStatus] = useState('');
  const [cvReady, setCvReady] = useState<any | null>(null);
  const [cvRegistry, setCvRegistry] = useState<any | null>(null);
  const [cvRegistryText, setCvRegistryText] = useState('');
  const [cvStatus, setCvStatus] = useState('');
  const [currentKey, setCurrentKey] = useState('');
  const masked = currentKey ? `${currentKey.slice(0, 6)}...${currentKey.slice(-4)}` : 'Not set';

  useEffect(() => {
    fetchToolInvocations(10)
      .then((data) => setTools(data.invocations || []))
      .catch((e) => setToolError(e.message || 'Failed to load tool invocations'));
    fetchDbReadiness()
      .then(setDbReady)
      .catch((e) => setDbReady({ error: e.message || 'DB readiness error' } as any));
    fetchCVReadiness()
      .then(setCvReady)
      .catch(() => setCvReady({ error: 'CV readiness unavailable' }));
    fetchTenantConfig('cv_model_registry')
      .then((r) => {
        setCvRegistry(r.value || {});
        setCvRegistryText(JSON.stringify(r.value || {}, null, 2));
      })
      .catch(() => {
        setCvRegistry({});
        setCvRegistryText('{}');
      });
    try {
      const k = (import.meta.env.VITE_API_KEY as string) || '';
      if (k) {
        setClientApiKey(k);
        setCurrentKey(k);
      }
    } catch {}
  }, []);

  useEffect(() => {
    if (!showPrefs) return;
    fetchPreferences('demo-user')
      .then((data) => setPrefs(data?.preferences || {}))
      .catch(() => setPrefs({}));
  }, [showPrefs]);

  return (
    <div className="stagger">
      <div className="grid-2">
        <div className="card">
          <h3>DB Readiness</h3>
          {!dbReady && <div className="page-sub">Checking...</div>}
          {dbReady && (
            <div className="list">
              <div className="list-item"><div>Engine</div><strong>{dbReady.engine || 'unknown'}</strong></div>
              <div className="list-item"><div>Dialect</div><strong>{dbReady.dialect || 'unknown'}</strong></div>
              <div className="list-item"><div>Connected</div><strong>{String(!!dbReady.connected)}</strong></div>
              <div className="list-item"><div>Migrations OK</div><strong>{String(!!dbReady.migrations_ok)}</strong></div>
              <div className="list-item"><div>Timescale Ready</div><strong>{String(!!dbReady.timescale_ready)}</strong></div>
              {dbReady.error && <div className="page-sub" style={{ color: '#9f2d1b' }}>Error: {dbReady.error}</div>}
            </div>
          )}
          <div style={{ marginTop: 10 }}>
            <button
              className="btn"
              onClick={async () => {
                try {
                  setDbStatus('Applying…');
                  const res = await ensureTimescale();
                  setDbReady(res);
                  setDbStatus('Applied');
                } catch (e:any) {
                  setDbStatus('Failed: ' + (e.message || e));
                }
              }}
            >Ensure Timescale</button>
            {dbStatus && <div className="page-sub" style={{ marginTop: 8 }}>{dbStatus}</div>}
          </div>
        </div>
        <div className="card">
          <h3>Admin Tools</h3>
          <div className="page-sub">Use Ensure Timescale when running Postgres to prepare time-series tables and extension.</div>
        </div>
      </div>
      <div className="grid-2">
        <div className="card">
          <h3>API Keys</h3>
          <div className="list">
            <div className="list-item"><div>Current key</div><strong>{masked}</strong></div>
          </div>
          <div style={{ marginTop: 10 }}>
            <input
              className="modal-input"
              placeholder="Paste new API key"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
            />
            <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
              <button
                className="btn"
                onClick={async () => {
                  if (!keyInput.trim()) return;
                  const next = keyInput.trim();
                  setClientApiKey(next);
                  try { await setApiKeyCookie(next); } catch {}
                  setCurrentKey(next);
                  setStatus('Saved to secure session cookie.');
                  setKeyInput('');
                }}
              >
                Save Key
              </button>
              <button
                className="btn secondary"
                onClick={async () => {
                  setClientApiKey('');
                  try { await clearApiKeyCookie(); } catch {}
                  setCurrentKey('');
                  setStatus('Key cleared.');
                }}
              >
                Clear
              </button>
              <button
                className="btn ghost"
                onClick={async () => {
                  try {
                    const me = await fetchMe();
                    setStatus(`Valid as ${me.role}`);
                  } catch {
                    setStatus('Invalid key.');
                  }
                }}
              >
                Test Key
              </button>
            </div>
            {status && <div className="page-sub" style={{ marginTop: 8 }}>{status}</div>}
          </div>
          <div style={{ marginTop: 10 }}>
            <button className="btn secondary">View Audit</button>
          </div>
        </div>
        <div className="card">
          <h3>Key Management</h3>
          <div className="page-sub">Server key management moved to Owner Console.</div>
          <div className="callout" style={{ marginTop: 10 }}>
            You can still store a local key here for developer testing, but rotate/add/remove server keys in Owner Console.
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>SDK & Sandbox</h3>
        <div className="list">
          <div className="list-item"><div>Widget SDK</div><strong>v0.9.3</strong></div>
          <div className="list-item"><div>Last deploy</div><strong>12 minutes ago</strong></div>
          <div className="list-item"><div>Latency p95</div><strong>480ms</strong></div>
        </div>
        <div style={{ marginTop: 10 }}>
          <button className="btn">Open API Console</button>
          <button className="btn secondary" style={{ marginLeft: 8 }}>View Logs</button>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>CV Readiness & Model Registry</h3>
        <div className="page-sub" style={{ marginTop: 6 }}>
          Use this to see what CV capabilities are actually enabled (weights/providers/config), and to override per-tenant CV registry settings.
        </div>
        <div className="grid-2" style={{ marginTop: 10 }}>
          <div className="card" style={{ padding: 14 }}>
            <div style={{ fontWeight: 700 }}>Readiness</div>
            <pre style={{ marginTop: 10, whiteSpace: 'pre-wrap' }}>{JSON.stringify(cvReady || {}, null, 2)}</pre>
          </div>
          <div className="card" style={{ padding: 14 }}>
            <div style={{ fontWeight: 700 }}>Tenant Override: `cv_model_registry`</div>
            <div className="page-sub" style={{ marginTop: 6 }}>
              Stored in `tenant_config_overrides` (tenant_id=global when omitted). Keep OCR disabled in production until you have a safe ingestion sandbox.
            </div>
            <textarea
              className="modal-input"
              style={{ minHeight: 200, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace' }}
              value={cvRegistryText}
              onChange={(e) => setCvRegistryText(e.target.value)}
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <button
                className="btn"
                onClick={async () => {
                  setCvStatus('');
                  try {
                    const parsed = JSON.parse(cvRegistryText || '{}');
                    await putTenantConfig('cv_model_registry', parsed);
                    setCvRegistry(parsed);
                    setCvStatus('Saved.');
                  } catch (e: any) {
                    setCvStatus(e?.message || 'Save failed');
                  }
                }}
              >
                Save Override
              </button>
              <button
                className="btn secondary"
                onClick={async () => {
                  try {
                    const r = await fetchTenantConfig('cv_model_registry');
                    setCvRegistry(r.value || {});
                    setCvRegistryText(JSON.stringify(r.value || {}, null, 2));
                    setCvStatus('Reloaded.');
                  } catch {
                    setCvStatus('Reload failed.');
                  }
                }}
              >
                Reload
              </button>
              {cvStatus && <span className="pill">{cvStatus}</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>BI / PowerBI Exports</h3>
        <div className="page-sub" style={{ marginTop: 6 }}>
          Owner/Developer-only export endpoints suitable for PowerBI “Web” connectors or scheduled pulls.
        </div>
        <div className="list" style={{ marginTop: 10 }}>
          {[
            { label: 'Unified CSV', path: '/api/v1/admin/powerbi/export.csv' },
            { label: 'Unified NDJSON', path: '/api/v1/admin/powerbi/export.ndjson' },
            { label: 'Decisions CSV', path: '/api/v1/admin/powerbi/export/decisions.csv' },
            { label: 'Orders CSV', path: '/api/v1/admin/powerbi/export/orders.csv' },
            { label: 'Security CSV', path: '/api/v1/admin/powerbi/export/security.csv' },
          ].map((e) => (
            <div className="list-item" key={e.path}>
              <div>{e.label}</div>
              <a className="mono" href={`${(import.meta.env.VITE_API_BASE as string) || window.location.origin}${e.path}`} target="_blank" rel="noreferrer">
                {e.path}
              </a>
            </div>
          ))}
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Tool Invocations (MCP Bridge)</h3>
        {toolError && <div className="page-sub" style={{ color: '#9f2d1b' }}>Error: {toolError}</div>}
        {!tools.length && !toolError && <div className="page-sub">No tool invocations yet.</div>}
        {!!tools.length && (
          <div className="list">
            {tools.map((t) => (
              <div key={t.id} className="list-item">
                <div>{t.tool} <span className="page-sub">{t.destination}</span></div>
                <strong>{t.severity}</strong>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Learned Preferences</h3>
        <div className="page-sub" style={{ marginTop: 6 }}>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input type="checkbox" checked={showPrefs} onChange={(e) => setShowPrefs(e.target.checked)} />
            Show preferences panel
          </label>
        </div>
        {showPrefs && (
          <div className="list" style={{ marginTop: 10 }}>
            {prefs?.prefs_meta
              ? Object.keys(prefs.prefs_meta).map((k) => (
                  <div key={k} className="list-item">
                    <div>{k}</div>
                    <strong>{Array.isArray(prefs.prefs_meta[k]?.value) ? prefs.prefs_meta[k].value.join(', ') : String(prefs.prefs_meta[k]?.value || '')}</strong>
                  </div>
                ))
              : <div className="page-sub">No preferences learned yet.</div>}
          </div>
        )}
      </div>
    </div>
  );
}
