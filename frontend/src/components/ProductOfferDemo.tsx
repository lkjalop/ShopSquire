import {useEffect,useState} from 'react';
import {apiFetch} from '../lib/csrf';
import {getOrCreateStoredUid} from '../lib/browserSession';

export default function ProductOfferDemo(){
 const [uid]=useState(getOrCreateStoredUid);const [state,setState]=useState<any>(null);
 const [caseId,setCaseId]=useState(new URLSearchParams(location.search).get('case_id')||'');
 const [need,setNeed]=useState('portable_backup');const [qty,setQty]=useState(1);
 const [offer,setOffer]=useState<any>(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const base='/api/v1/demo/product-offer-cases';
 const headers={'x-tenant-id':'synthetic-bundles'};
 async function load(id=caseId){if(id)setState(await apiFetch(`${base}/${id}?uid=${encodeURIComponent(uid)}`,{headers}));}
 useEffect(()=>{void load().catch(e=>setError(String(e)));},[caseId]);
 async function act(action:string,target=''){
  setBusy(true);setError('');
  try{
   if(action==='start'){
    const value=await apiFetch<any>(base,{method:'POST',headers,body:JSON.stringify({uid})});setState(value);setCaseId(value.case_id);
    history.replaceState(null,'',`?surface=product-offers&case_id=${value.case_id}`);
   }else if(action==='propose'){
    setOffer(null);setOffer(await apiFetch(`${base}/${caseId}/offers`,{method:'POST',headers,body:JSON.stringify({uid,expected_revision:state.case_revision,target_configuration_id:target,need,quantity:qty})}));
   }else if(action==='decline'){
    await apiFetch(`${base}/${caseId}/offers/${offer.id}/decline`,{method:'POST',headers,body:JSON.stringify({uid})});setOffer(null);
   }else if(action==='accept'){
    const result=await apiFetch<any>(`${base}/${caseId}/offers/${offer.id}/accept`,{method:'POST',headers,body:JSON.stringify({uid})});
    setOffer({...offer,status:result.status});await load();
   }
  }catch(e){
   const message=e instanceof Error?e.message:'';
   const reasons:Record<string,string>={
    unambiguous_relationship_evidence_required:'Compatibility evidence is missing or conflicting. No offer can be made.',
    current_supported_relationship_required:'Current evidence does not support this pairing. No offer can be made.',
    offer_stock_unavailable:'There is not enough available stock for this offer.',
    offer_evidence_or_price_changed:'The evidence or price changed. Review a fresh offer before accepting.',
    offer_not_current:'This offer expired, was declined or was replaced. Review a fresh offer.',
    cart_version_conflict:'Your cart changed in another action. Reload it and review a fresh offer.',
    case_revision_conflict:'Your requirements changed. Reload the case and review a fresh offer.',
   };
   setError(Object.entries(reasons).find(([code])=>message.includes(code))?.[1]||'The offer is unavailable. Your cart has not been changed by this request.');
  }
  finally{setBusy(false);}
 }
 return <main style={{maxWidth:1000,margin:'20px auto',padding:24}}>
  <h1>Fictional upgrades and bundles</h1>
  <p>Compatibility and benefits here are invented fixture evidence tied to existing catalogue identities. They do not certify real products. Accepting changes a draft cart only; it does not reserve stock, send a message or authorize payment.</p>
  {!caseId&&<button disabled={busy} onClick={()=>act('start')}>Start fictional offer case</button>}
  {state&&<><p>Base: {state.base.label} ({state.base.sku}). Case revision {state.case_revision}.</p>
   <label>Buyer need <select aria-label="Offer buyer need" value={need} disabled={busy} onChange={e=>{setNeed(e.target.value);setOffer(null);}}>
    <option value="portable_backup">Portable backup storage</option><option value="memory_capacity">Greater memory capacity</option>
   </select></label>{' '}
   <label>Units <input aria-label="Offer quantity" type="number" min="1" max="10" value={qty} disabled={busy} onChange={e=>{setQty(Number(e.target.value));setOffer(null);}}/></label>
   <ul>{state.candidates.map((candidate:any)=><li key={candidate.sku}>
    {candidate.label} ({candidate.sku}) <button disabled={busy} onClick={()=>act('propose',candidate.configuration_id)}>Review {candidate.label}</button>
   </li>)}</ul>
   {offer&&<section aria-label="Product offer review"><h2>{offer.kind==='upgrade'?'Upgrade':'Bundle'}: {offer.status}</h2>
    <p>{offer.benefit}</p><p>Base total: {offer.currency} {(offer.base_total_cents/100).toFixed(2)}. Increment: {offer.currency} {(offer.incremental_cents/100).toFixed(2)}. Total: {offer.currency} {(offer.total_cents/100).toFixed(2)}.</p>
    <p>Source: {offer.evidence.source_id}. {offer.evidence.excerpt}</p><p>Offer expires {offer.expires_at}. Applied pricing discount: {offer.currency} {(offer.applied_discount_cents/100).toFixed(2)}. {offer.discount_approval_required?'Further discount requires separate approval.':''}</p>
    <button disabled={busy||offer.status!=='proposed'} onClick={()=>act('accept')}>Accept exact product offer</button>{' '}
    <button disabled={busy||offer.status!=='proposed'} onClick={()=>act('decline')}>Decline offer</button>
   </section>}
   <section aria-label="Durable draft cart"><h2>Draft cart</h2><p>Cart version {state.cart?.version}. Purchase authority: none.</p>
    {(state.cart?.items||[]).length===0?<p>Empty</p>:<ul>{state.cart.items.map((line:any)=><li key={line.sku}>{line.sku}: {line.quantity} units</li>)}</ul>}
   </section>
  </>}
  {error&&<p role="alert">{error}</p>}
 </main>;
}
