import React, { useState } from 'react';
import { apiUrl } from '../lib/api';
import { getOwnerApiKey } from '../lib/browserSession';

export default function MerchantDecisionCard() {
  const [tenant, setTenant] = useState('');
  const [sku, setSku] = useState('');
  const [query,setQuery]=useState('supplier delivery capacity and replenishment');
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true); setResult(null); setError('');
    try {
      const response = await fetch(apiUrl(`/api/v1/merchant/intelligence/replenishment/${encodeURIComponent(sku.trim())}?query=${encodeURIComponent(query)}`), {
        credentials: 'include',
        headers: { 'x-api-key': getOwnerApiKey(), 'x-tenant-id': tenant.trim() },
      });
      if (!response.ok) throw new Error(response.status === 404 ? 'No decision dataset exists for this tenant and SKU.' : `Decision unavailable (${response.status}).`);
      setResult(await response.json());
    } catch (e) { setError(e instanceof Error ? e.message : 'Decision unavailable.'); }
    finally { setBusy(false); }
  }
  const decision = result?.decision;
  return <section aria-label="Replenishment decision" style={{ padding: 20 }}>
    <h3>Replenishment decision</h3>
    <p>Review stock and dated supplier evidence before deciding whether to replenish.</p>
    <label>Tenant <input aria-label="Decision tenant" value={tenant} disabled={busy} onChange={e => { setTenant(e.target.value); setResult(null); }} /></label>{' '}
    <label>SKU <input aria-label="Decision SKU" value={sku} disabled={busy} onChange={e => { setSku(e.target.value); setResult(null); }} /></label>{' '}
    <label>Evidence question <input aria-label="Merchant evidence question" maxLength={200} value={query} disabled={busy} onChange={e=>{setQuery(e.target.value);setResult(null);}}/></label>{' '}
    <button disabled={busy || !tenant.trim() || !sku.trim()} onClick={load}>{busy ? 'Loading decision…' : 'Review replenishment'}</button>
    {error && <p role="alert">{error}</p>}
    {decision && <div role="status">
      <p><strong>Simulation only · Advisory · No purchase authorized</strong></p>
      <p>Evidence as of {result.as_of} · {result.covered_days} covered days</p>
      {decision.status === 'blocked' ? <p>Decision blocked: {decision.reason}</p> : <>
        <h4>{decision.decision === 'review_replenishment' ? 'Review a replenishment order' : 'Wait and monitor'}</h4>
        <p>Available: {decision.available_units} units. Incoming: {decision.incoming_units} units. Target: {decision.target_units} units.</p>
        <p>Proposed: {decision.proposed_units} units. Total landed cost: {decision.currency} {(decision.total_cost_minor / 100).toFixed(2)}.</p>
        <p>{decision.explanation}</p>
        {decision.limitation && <p>{decision.limitation} Stockout days: {decision.censored_days}.</p>}
        <p>Supplier quote expires {result.quote.expires_at}.</p>
        <details><summary>Source evidence</summary><ul>{decision.evidence_ids.map((id: string) => <li key={id}>{id}</li>)}</ul></details>
      </>}
      {result.evidence&&<section aria-label="Reviewed market evidence">
        <h4>Reviewed market evidence</h4>
        <p>Retrieval: {result.evidence.status}. {result.evidence.retrieval?.dense_provider==='not_called'
          ? 'No eligible evidence was available for retrieval.'
          : result.evidence.retrieval?.degraded
            ? 'Semantic retrieval unavailable; lexical retrieval only.'
            : result.evidence.status==='empty'
              ? 'Retrieval returned no relevant matches.'
              : 'Lexical and semantic retrieval completed.'}</p>
        <p>Supporting context only. These notes do not change the baseline calculation or authorize an order.</p>
        {result.evidence.status==='conflicting'&&<p role="alert">Current sources disagree. Review the conflicting observations before using them for a decision.</p>}
        <ul>{result.evidence.hits.map((hit:any)=><li key={hit.id}>
          <strong>{hit.source_id}</strong> · observed {hit.observed_at} · valid until {hit.expires_at}
          <ul>{hit.claims.map((claim:any,index:number)=><li key={index}>{claim.field}: {claim.value} {claim.unit}. Source excerpt: {claim.quote}</li>)}</ul>
        </li>)}</ul>
        {result.evidence.withheld.length>0&&<details><summary>Withheld evidence</summary><ul>{result.evidence.withheld.map((row:any)=><li key={row.id}>{row.id}: {row.reason}</li>)}</ul></details>}
      </section>}
    </div>}
  </section>;
}
