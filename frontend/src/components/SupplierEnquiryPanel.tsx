import React,{useState} from 'react';
import {apiFetch} from '../lib/csrf';
import {getOwnerApiKey} from '../lib/browserSession';

export default function SupplierEnquiryPanel(){
 const [tenant,setTenant]=useState('');const [caseId,setCaseId]=useState('');
 const [revision,setRevision]=useState(1);const [reference,setReference]=useState('');
 const [id,setId]=useState('');const [row,setRow]=useState<any>(null);
 const [includeBudget,setIncludeBudget]=useState(true);
 const [replyText,setReplyText]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const [evidence,setEvidence]=useState('');const [provider,setProvider]=useState('');
 const [outcome,setOutcome]=useState('not_delivered');const [renewal,setRenewal]=useState('');
 const base='/api/v1/admin/inventory/supplier-enquiries';
 const headers=()=>({'x-api-key':getOwnerApiKey(),'x-tenant-id':tenant.trim()});
 async function act(action:string){
  setBusy(true);setError('');
  try{
   if(action==='create'){
    const value=await apiFetch<any>(base,{method:'POST',headers:headers(),body:JSON.stringify({case_id:caseId,expected_revision:revision,supplier_ref:'fictional-distributor',source_reference:reference})});
    setId(value.id);setRow(value);setIncludeBudget(value.draft_artifact?.include_budget??true);
   }else if(action==='renew'){
    const value=await apiFetch<any>(`${base}/${id}/renew`,{method:'POST',headers:headers(),body:JSON.stringify({expected_revision:revision,reference:renewal})});
    setId(value.id);setRow(value);setIncludeBudget(value.draft_artifact?.include_budget??true);
   }else{
    if(action==='reply')await apiFetch(`${base}/${id}/simulated-replies`,{method:'POST',headers:headers(),body:JSON.stringify(JSON.parse(replyText))});
    else if(action==='recovery')await apiFetch(`${base}/${id}/recovery`,{method:'POST',headers:headers(),body:JSON.stringify({outcome,evidence_ref:evidence,provider_ref:outcome==='submitted'?provider:''})});
    else if(action==='draft')await apiFetch(`${base}/${id}/draft`,{method:'POST',headers:headers(),body:JSON.stringify({expected_version:row.draft_version,include_budget:includeBudget})});
    else if(action!=='load')await apiFetch(`${base}/${id}/${action}`,{method:'POST',headers:headers()});
    const value=await apiFetch<any>(`${base}/${id}`,{headers:headers()});
    setRow(value);setIncludeBudget(value.draft_artifact?.include_budget??true);
   }
  }catch(e){setError(e instanceof Error?e.message:'Supplier workflow unavailable');}
  finally{setBusy(false);}
 }
 return <section aria-label="Supplier enquiries" style={{padding:20}}>
  <h3>Simulated supplier enquiries</h3><p>Ask the fictional distributor to cover an accepted buyer request's stock shortfall. A different enrolled person must approve the exact enquiry. Replies require review; no purchase is authorized.</p>
  <fieldset disabled={busy}><legend>Accepted buyer request</legend>
   <label>Tenant <input aria-label="Supplier tenant" value={tenant} onChange={e=>{setTenant(e.target.value);setRow(null);}}/></label>{' '}
   <label>Case <input aria-label="Supplier case ID" value={caseId} onChange={e=>setCaseId(e.target.value)}/></label>{' '}
   <label>Revision <input aria-label="Supplier case revision" type="number" min="1" value={revision} onChange={e=>setRevision(Number(e.target.value))}/></label>{' '}
   <label>Enquiry reference <input aria-label="Enquiry reference" value={reference} onChange={e=>setReference(e.target.value)}/></label>{' '}
   <button disabled={!tenant||!caseId||reference.length<8} onClick={()=>act('create')}>Draft shortfall enquiry</button>
  </fieldset>
  <label>Enquiry ID <input aria-label="Enquiry ID" value={id} disabled={busy} onChange={e=>{setId(e.target.value);setRow(null);}}/></label>{' '}
  <button disabled={busy||!tenant||!id} onClick={()=>act('load')}>Load enquiry</button>{' '}
  <button disabled={busy||row?.status!=='pending'} onClick={()=>act('approve')}>Approve enquiry</button>{' '}
  <button disabled={busy||row?.status!=='approved'||row?.approval_state!=='current'||!['not_dispatched','pending','failed'].includes(row?.delivery_status)} onClick={()=>act('dispatch')}>Send through fake transport</button>
  {error&&<p role="alert">{error}</p>}
  {row&&<><div role="status"><p>Enquiry {row.id}: {row.status}. Delivery: {row.delivery_status}. Transport attempts: {row.transport_attempts}.</p>
   <p>Approval: {row.approval_state}.</p>
   <p>Requested {row.requested_quantity}; shortfall {row.shortfall}; SKU {row.sku}; case revision {row.case_revision}.</p>
   <p>Server-calculated request value: {row.currency} {(row.value_cents/100).toFixed(2)}. Purchase authority: none.</p>
   <p>{row.reply_status==='awaiting_reply'?'Awaiting a supplier reply. Silence is not acceptance.':'Supplier replies received.'}</p></div>
   {row.message&&<section aria-label="Exact enquiry message">
    <h4>Review enquiry message</h4>
    {row.draft_artifact&&<p>Draft version {row.draft_version}. Changes require fresh independent approval.</p>}
    <dl><dt>To</dt><dd>{row.message.recipient}</dd><dt>Subject</dt><dd>{row.message.subject}</dd></dl>
    <pre style={{whiteSpace:'pre-wrap'}}>{row.message.body}</pre>
    {row.draft_artifact&&<fieldset disabled={busy||row.delivery_status!=='not_dispatched'}>
     <legend>Budget disclosure</legend>
     <label><input type="checkbox" aria-label="Include buyer budget in supplier message" checked={includeBudget} onChange={e=>setIncludeBudget(e.target.checked)}/> Include buyer budget in supplier message</label>{' '}
     <button disabled={includeBudget===row.draft_artifact.include_budget} onClick={()=>act('draft')}>Save revised draft for review</button>
    </fieldset>}
   </section>}
   <details><summary>Review and recover enquiry</summary>
    <p>Revocation stops future dispatch. It cannot undo a submitted message. Record an observed provider outcome only after checking its evidence; this is an operator attestation, not supplier acknowledgement.</p>
    <button disabled={busy||row.approval_state!=='current'} onClick={()=>act('revoke-approval')}>Revoke enquiry approval</button>
    <fieldset disabled={busy||row.delivery_status!=='reconciliation_required'}><legend>Observed provider outcome</legend>
     <label>Outcome <select aria-label="Provider outcome" value={outcome} onChange={e=>setOutcome(e.target.value)}><option value="not_delivered">Confirmed not delivered</option><option value="submitted">Confirmed submitted</option></select></label>
     <label>Evidence reference <input aria-label="Recovery evidence reference" value={evidence} onChange={e=>setEvidence(e.target.value)}/></label>
     {outcome==='submitted'&&<label>Provider reference <input aria-label="Recovery provider reference" value={provider} onChange={e=>setProvider(e.target.value)}/></label>}
     <button disabled={!evidence.trim()||(outcome==='submitted'&&!provider.trim())} onClick={()=>act('recovery')}>Record observed outcome</button>
    </fieldset>
    <p>A replacement uses the current accepted case revision entered above and requires fresh approval from a different person.</p>
    <label>Replacement reference <input aria-label="Replacement reference" value={renewal} onChange={e=>setRenewal(e.target.value)}/></label>
    <button disabled={busy||!renewal.trim()||!['not_dispatched','blocked_authority','resolved_not_delivered'].includes(row.delivery_status)||(row.approval_state==='current'&&row.delivery_status!=='resolved_not_delivered')} onClick={()=>act('renew')}>Draft replacement enquiry</button>
   </details>
   <details><summary>Simulate a supplier reply</summary>
    <p>Operator simulation input. Use a message ID, enrolled sender reference and structured quote terms; this is not an authenticated external mailbox.</p>
    <label>Reply JSON <textarea aria-label="Simulated supplier reply" rows={8} cols={90} value={replyText} onChange={e=>setReplyText(e.target.value)}/></label>
    <button disabled={busy||row.delivery_status!=='sent'||!replyText} onClick={()=>act('reply')}>Record simulated reply</button>
   </details>
   <ul>{row.quotes.map((q:any)=><li key={q.id} data-testid={`supplier-quote-${q.id}`}>
    {q.terms.sku}: {q.terms.quantity} units; {q.status}; {q.reason||q.assessment.coverage}.
    <p>Freight: {q.terms.currency} {(q.terms.freight_cents/100).toFixed(2)}. Delivery: {q.terms.lead_days} days. Valid until {q.terms.expires_at}.</p>
    <p>{q.assessment.eligible&&q.assessment.landed_cost_cents!==null?`Reviewed landed cost: ${q.terms.currency} ${(q.assessment.landed_cost_cents/100).toFixed(2)}`:'No usable landed-cost commitment.'} Purchase authority: none.</p>
    <button disabled={busy||q.status!=='review_required'||!!q.reason} onClick={()=>act(`replies/${q.id}/review`)}>Review quote {q.id}</button>
   </li>)}</ul>
  </>}
 </section>;
}
