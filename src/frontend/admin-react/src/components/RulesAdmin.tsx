import React, { useEffect, useMemo, useState } from 'react';
import {
  createRule,
  deleteRule,
  listRules,
  previewRule,
  updateRule,
  type RuleDefinition,
} from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

const domains = ['recommend', 'returns', 'inventory', 'email_security', 'policy', 'orchestrator'];

export function RulesAdmin({ role }: Props) {
  const [rules, setRules] = useState<RuleDefinition[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [domain, setDomain] = useState<string>('recommend');
  const [tenantId, setTenantId] = useState<string>('');
  const [selected, setSelected] = useState<RuleDefinition | null>(null);
  const [editing, setEditing] = useState<Partial<RuleDefinition>>({});
  const [previewText, setPreviewText] = useState<string>('show me gaming laptops under $1500');
  const [previewOut, setPreviewOut] = useState<any>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const canEdit = role === 'owner' || role === 'developer';

  const reload = async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listRules({ tenantId: tenantId || undefined, domain: domain || undefined });
      setRules(rows);
    } catch (e: any) {
      setError(e?.message || 'Failed to load rules');
      setRules([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domain, tenantId]);

  const sorted = useMemo(() => {
    return [...(rules || [])].sort((a, b) => (a.priority || 100) - (b.priority || 100));
  }, [rules]);

  const openNew = () => {
    setSelected({ id: '', title: '', priority: 100, active: 1, domain } as any);
    setEditing({ title: '', priority: 100, pattern: '', expression: '', tenant_id: tenantId || null, domain, active: 1 });
  };

  const openEdit = (r: RuleDefinition) => {
    setSelected(r);
    setEditing({ ...r });
  };

  const save = async () => {
    if (!canEdit) return;
    const payload = { ...editing, domain: editing.domain || domain };
    if (!payload.title || !String(payload.title).trim()) {
      alert('Title is required');
      return;
    }
    try {
      if (selected?.id) {
        await updateRule(selected.id, payload);
      } else {
        await createRule(payload);
      }
      setSelected(null);
      setEditing({});
      await reload();
    } catch (e: any) {
      alert(e?.message || 'Save failed');
    }
  };

  const remove = async () => {
    if (!canEdit) return;
    if (!selected?.id) return;
    if (!confirm('Delete this rule?')) return;
    try {
      await deleteRule(selected.id);
      setSelected(null);
      setEditing({});
      await reload();
    } catch (e: any) {
      alert(e?.message || 'Delete failed');
    }
  };

  const runPreview = async () => {
    setPreviewLoading(true);
    setPreviewOut(null);
    try {
      const out = await previewRule({ text: previewText, tenant_id: tenantId || undefined, domain: domain || undefined });
      setPreviewOut(out);
    } catch (e: any) {
      setPreviewOut({ error: e?.message || 'Preview failed' });
    } finally {
      setPreviewLoading(false);
    }
  };

  return (
    <div className="stagger">
      <div className="card">
        <h3>Rules Admin</h3>
        <div className="page-sub">DB-backed rules with priority ordering (lower number = earlier match).</div>
        {!canEdit && (
          <div className="callout" style={{ marginTop: 10 }}>
            Read-only. Use an Owner/Developer key to create or edit rules.
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <select className="modal-input" value={domain} onChange={(e) => setDomain(e.target.value)}>
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <input className="modal-input" placeholder="tenant_id (optional)" value={tenantId} onChange={(e) => setTenantId(e.target.value)} />
          <button className="btn secondary" onClick={() => reload()}>
            Refresh
          </button>
          <button className="btn" onClick={() => openNew()} disabled={!canEdit}>
            New Rule
          </button>
        </div>
        {loading && <div className="page-sub" style={{ marginTop: 8 }}>Loading…</div>}
        {error && <div className="page-sub" style={{ marginTop: 8, color: '#9f2d1b' }}>Error: {error}</div>}
        <div style={{ marginTop: 10 }}>
          {!sorted.length && !loading && <div className="page-sub">No rules for this domain/tenant.</div>}
          {!!sorted.length && (
            <table className="table">
              <thead>
                <tr>
                  <th>Priority</th>
                  <th>Title</th>
                  <th>Pattern</th>
                  <th>Tenant</th>
                  <th>Active</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.id}>
                    <td>{r.priority}</td>
                    <td>{r.title}</td>
                    <td className="mono" style={{ maxWidth: 320, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {r.pattern || '-'}
                    </td>
                    <td className="mono">{r.tenant_id || '-'}</td>
                    <td>{String(r.active ?? 1)}</td>
                    <td>
                      <button className="btn secondary" onClick={() => openEdit(r)}>
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Rule Preview</h3>
        <div className="page-sub">Runs the central `RuleEngine` against text (no persistence).</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10, flexWrap: 'wrap' }}>
          <input className="modal-input" style={{ flex: 1, minWidth: 260 }} value={previewText} onChange={(e) => setPreviewText(e.target.value)} />
          <button className="btn" onClick={() => runPreview()}>
            Preview
          </button>
        </div>
        {previewLoading && <div className="page-sub" style={{ marginTop: 8 }}>Evaluating…</div>}
        {previewOut && <pre className="panel" style={{ marginTop: 10 }}>{JSON.stringify(previewOut, null, 2)}</pre>}
      </div>

      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{selected.id ? 'Edit Rule' : 'New Rule'}</h3>
            <p className="page-sub">Domain: <span className="mono">{String(editing.domain || domain)}</span></p>
            <div className="grid-2">
              <div>
                <label className="page-sub">Title</label>
                <input className="modal-input" value={String(editing.title || '')} onChange={(e) => setEditing((p) => ({ ...p, title: e.target.value }))} />
              </div>
              <div>
                <label className="page-sub">Priority</label>
                <input
                  className="modal-input"
                  type="number"
                  value={String(editing.priority ?? 100)}
                  onChange={(e) => setEditing((p) => ({ ...p, priority: parseInt(e.target.value, 10) || 100 }))}
                />
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <label className="page-sub">Pattern (regex)</label>
              <input className="modal-input" value={String(editing.pattern || '')} onChange={(e) => setEditing((p) => ({ ...p, pattern: e.target.value }))} />
            </div>
            <div style={{ marginTop: 10 }}>
              <label className="page-sub">Tenant (optional)</label>
              <input className="modal-input" value={String(editing.tenant_id || '')} onChange={(e) => setEditing((p) => ({ ...p, tenant_id: e.target.value || null }))} />
            </div>
            <div style={{ marginTop: 10 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={Boolean(editing.active ?? 1)} onChange={(e) => setEditing((p) => ({ ...p, active: e.target.checked ? 1 : 0 }))} />
                <span className="page-sub">Active</span>
              </label>
            </div>
            <div className="modal-actions">
              {selected.id && (
                <button className="btn secondary" onClick={() => remove()} disabled={!canEdit}>
                  Delete
                </button>
              )}
              <button className="btn secondary" onClick={() => setSelected(null)}>
                Cancel
              </button>
              <button className="btn" onClick={() => save()} disabled={!canEdit}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

