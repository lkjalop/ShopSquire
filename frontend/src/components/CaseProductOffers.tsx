import {useEffect,useState} from 'react';
import {apiFetch} from '../lib/csrf';
import {apiRequestHeaders} from '../lib/api';

export default function CaseProductOffers({caseId,uid,sku,revision,onAccepted}:{caseId:string;uid:string;sku:string;revision?:number;onAccepted:(revision?:number)=>void}){
 const [options,setOptions]=useState<any>(null),[offer,setOffer]=useState<any>(null);
 const [quantity,setQuantity]=useState(1),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const base=`/api/v1/shopping-cases/${encodeURIComponent(caseId)}`;
 useEffect(()=>{
  let current=true;setOptions(null);setOffer(null);setError('');
  apiFetch(`${base}/product-offer-options?uid=${encodeURIComponent(uid)}&sku=${encodeURIComponent(sku)}`,{headers:apiRequestHeaders()})
   .then(value=>{if(current)setOptions(value);}).catch(()=>{if(current)setError('Supported product options are unavailable.');});
  return()=>{current=false;};
 },[caseId,uid,sku,revision]);
 async function act(action:string,candidate?:any){
  setBusy(true);setError('');
  try{
   if(action==='review'){
    setOffer(null);
    setOffer(await apiFetch(`${base}/product-offers`,{method:'POST',headers:apiRequestHeaders(),body:JSON.stringify({uid,expected_revision:options.case_revision,
      base_configuration_id:options.base_configuration_id,target_configuration_id:candidate.configuration_id,need:candidate.need,quantity})}));
   }else{
    const result=await apiFetch<any>(`${base}/product-offers/${offer.id}/${action}`,{method:'POST',headers:apiRequestHeaders(),body:JSON.stringify({uid})});
    setOffer(null);if(action==='accept')onAccepted(result.case_revision);
   }
  }catch(e){setError(`The offer could not be ${action==='review'?'prepared':'accepted or declined'}. Refresh the case and review current evidence. ${e instanceof Error?e.message:''}`);}
  finally{setBusy(false);}
 }
 return <section aria-label="Supported product options"><h3>Optional upgrades and accessories</h3>
  <p>Review the supported benefit and total before accepting. Acceptance changes your draft cart and case revision; it does not reserve stock or authorize payment.</p>
  {options&&options.candidates.length===0&&<p>No current supported pairing is available for this exact configuration.</p>}
  {!!options?.candidates.length&&<><label>Offer units <input aria-label="Case offer units" type="number" min="1" max="10000" value={quantity} disabled={busy} onChange={e=>{setQuantity(Number(e.target.value));setOffer(null);}}/></label>
   <ul>{options.candidates.map((candidate:any)=><li key={candidate.configuration_id+candidate.need}>{candidate.label}: {candidate.benefit}
    <button disabled={busy||!Number.isInteger(quantity)||quantity<1||quantity>10000} onClick={()=>void act('review',candidate)}>Review option {candidate.sku}</button></li>)}</ul></>}
  {offer&&<section aria-label="Case product offer review"><p>{offer.benefit}</p>
   <p>Increment: {offer.currency} {(offer.incremental_cents/100).toFixed(2)}. Total: {offer.currency} {(offer.total_cents/100).toFixed(2)}.</p>
   <p>Evidence: {offer.evidence.source_id}. {offer.evidence.excerpt}</p><p>Offer expires {offer.expires_at}.</p>
   <button disabled={busy} onClick={()=>void act('accept')}>Accept exact case offer</button>
   <button disabled={busy} onClick={()=>void act('decline')}>Decline case offer</button>
  </section>}
  {error&&<p role="alert">{error}</p>}
 </section>;
}
