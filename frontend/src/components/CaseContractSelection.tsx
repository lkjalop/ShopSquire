import { useEffect, useRef, useState } from 'react';
import { apiRequestHeaders, apiUrl } from '../lib/api';

type Selection = {state: string; case_revision: number; binding_id?: string; contract_id?: string};
type Contract = {id: string; revision: string; context: {subject: string; version: string; platform: string; workload: string};
  exclusions: string[]; obligations: Array<{id: string; attribute: string; tier: string}>};
type Projection = {selection: Selection; contracts: Contract[]};

export default function CaseContractSelection({caseId, uid, onChange, tenantId, revision}: {
  caseId: string; uid: string; onChange?: (selection: Selection) => void; tenantId?: string; revision?:number;
}) {
  const [projection, setProjection] = useState<Projection | null>(null);
  const [chosen, setChosen] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const generation = useRef(0);
  const endpoint = `/api/v1/shopping-cases/${encodeURIComponent(caseId)}/requirement-contract`;
  useEffect(() => {
    const current = ++generation.current;
    const controller = new AbortController();
    setProjection(null); setChosen(''); setError(''); setBusy(true);
    fetch(apiUrl(`${endpoint}?uid=${encodeURIComponent(uid)}`), {signal:controller.signal, headers: apiRequestHeaders(tenantId ? {'X-Tenant-Id':tenantId} : {}), credentials:'include'})
      .then(async response => { if (!response.ok) throw new Error(`Unable to load requirements (${response.status})`); return response.json(); })
      .then(data => { if (generation.current === current) setProjection(data); })
      .catch(reason => { if (generation.current === current) setError(String(reason)); })
      .finally(() => { if (generation.current === current) setBusy(false); });
    return () => { generation.current++; controller.abort(); };
  }, [endpoint, uid, tenantId, revision, reload]);
  const contract = projection?.contracts.find(item => item.id === chosen);
  async function update(revoke: boolean) {
    if (!projection || (!revoke && !contract)) return;
    const current = generation.current;
    setBusy(true); setError('');
    const body = {uid, expected_revision: projection.selection.case_revision,
      ...(revoke ? {binding_id:projection.selection.binding_id} :
        {contract_id:contract!.id,contract_revision:contract!.revision,context:contract!.context})};
    try {
      const response = await fetch(apiUrl(endpoint + (revoke ? '/revoke' : '')), {
        method:revoke ? 'POST' : 'PUT',credentials:'include',headers:apiRequestHeaders(tenantId ? {'X-Tenant-Id':tenantId} : {},true),body:JSON.stringify(body),
      });
      if (!response.ok) throw new Error(response.status === 409
        ? 'This case or its requirements changed. Reload before choosing again.' : `Selection failed (${response.status})`);
      const data: Projection = await response.json();
      if (generation.current === current) { setProjection(data); setChosen(''); onChange?.(data.selection); }
    } catch (reason) { if (generation.current === current) setError(String(reason)); }
    finally { if (generation.current === current) setBusy(false); }
  }
  return <section aria-label="Buyer requirement selection" style={{padding:16,border:'1px solid #ddd',borderRadius:8}}>
    <h3>Choose the requirements to evaluate</h3>
    <p>Select the exact version, platform and workload. This selects evaluation criteria; it does not qualify a product or approve a purchase.</p>
    {error && <p role="alert">{error}</p>}
    {error && !projection && <button disabled={busy} onClick={()=>setReload(value=>value+1)}>Retry loading requirements</button>}
    {projection && <>
      <p>Selection status: <strong data-testid="contract-state">{projection.selection.state}</strong></p>
      <label>Requirement scope <select value={chosen} disabled={busy} onChange={event=>setChosen(event.target.value)}>
        <option value="">Choose a scope</option>
        {projection.contracts.map(item=><option key={item.id} value={item.id}>
          {item.context.subject} {item.context.version} · {item.context.platform} · {item.context.workload}
        </option>)}
      </select></label>
      {contract && <div><p>Required checks: {contract.obligations.map(item=>`${item.attribute} (${item.tier})`).join(', ')}</p>
        <p>Excluded: {contract.exclusions.join('; ') || 'No additional exclusions listed'}</p></div>}
      <button disabled={busy || !contract} onClick={()=>void update(false)}>Select requirements</button>
      <button disabled={busy || !projection.selection.binding_id || projection.selection.state === 'revoked'}
        onClick={()=>void update(true)}>Revoke selection</button>
    </>}
    {busy && <p role="status">Updating requirements…</p>}
  </section>;
}
