import {useEffect,useRef,useState} from 'react';
import {apiRequestHeaders,apiUrl} from '../lib/api';

type Quote={quote_id:string;sku:string;quantity:number;uncovered_quantity:number;coverage:string;
  eligible:boolean;reason:string;currency:string;unit_price_cents:number|null;freight_cents:number;
  total_price_cents:number|null;estimated_lead_days:number;expires_at:string;minimum_order:number;
  selection_digest:string;covered_order_quantity:number;covered_order_total_price_cents:number|null;
  requirement_assessment?:{deadline_status:string;budget_status:string;required_by:string|null}};
type View={status:string;quotes:Quote[];case_revision:number};
type Selection={status:string;selection_id?:string;quote?:Quote};

export default function BuyerSupplierQuotes({caseId,uid,revision,tenantId}:{caseId:string;uid:string;revision?:number;tenantId?:string}){
  const [view,setView]=useState<View|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [selection,setSelection]=useState<Selection|null>(null);
  const generation=useRef(0);
  async function refresh(signal?:AbortSignal){
    const request=++generation.current;setBusy(true);setError('');setView(null);setSelection(null);
    try{
      const options={credentials:'include' as const,signal,headers:apiRequestHeaders(tenantId?{'X-Tenant-ID':tenantId}:{})};
      const base=`/api/v1/shopping-cases/${encodeURIComponent(caseId)}`;
      const [response,selected]=await Promise.all([
        fetch(apiUrl(`${base}/supplier-quotes?uid=${encodeURIComponent(uid)}`),options),
        fetch(apiUrl(`${base}/supplier-quote-selection?uid=${encodeURIComponent(uid)}`),options)]);
      if(!response.ok)throw new Error(`Supplier quotes unavailable (${response.status})`);
      if(!selected.ok)throw new Error(`Supplier selection unavailable (${selected.status})`);
      const [data,accepted]=await Promise.all([response.json(),selected.json()]);
      if(request===generation.current){setView(data);setSelection(accepted);}
    }catch(reason){if(request===generation.current&&!signal?.aborted)setError(String(reason));}
    finally{if(request===generation.current)setBusy(false);}
  }
  useEffect(()=>{
    const controller=new AbortController();void refresh(controller.signal);
    return()=>{generation.current++;controller.abort();};
  },[caseId,uid,revision,tenantId]);
  async function select(quote:Quote){
    if(!view)return;
    const request=++generation.current;setBusy(true);setError('');
    try{
      const response=await fetch(apiUrl(`/api/v1/shopping-cases/${encodeURIComponent(caseId)}/supplier-quote-selection`),{
        method:'POST',credentials:'include',headers:apiRequestHeaders({'Content-Type':'application/json',...(tenantId?{'X-Tenant-ID':tenantId}:{})}),
        body:JSON.stringify({uid,expected_revision:view.case_revision,quote_id:quote.quote_id,expected_digest:quote.selection_digest})});
      const data=await response.json();
      if(!response.ok)throw new Error(`Selection not accepted: ${String(data.detail||response.status)}. Refresh the quotes.`);
      if(request===generation.current)setSelection(data);
    }catch(reason){if(request===generation.current)setError(String(reason));}
    finally{if(request===generation.current)setBusy(false);}
  }
  const money=(value:number,currency:string)=>new Intl.NumberFormat('en-AU',{style:'currency',currency}).format(value/100);
  return <section aria-label="Reviewed supplier options">
    <h3>Reviewed supplier options</h3>
    <p>Estimates use the current shop price plus disclosed freight. They do not reserve supplier stock or authorize a purchase. Delivery is estimated.</p>
    <button disabled={busy} onClick={()=>void refresh()}>Refresh supplier quotes</button>
    {error&&<p role="alert">{error}</p>}
    {selection?.status==='current'&&<p role="status">Sourcing estimate selected for operator review. No supplier stock is reserved and no purchase is authorized.</p>}
    {selection?.status==='revalidation_required'&&<p role="status">Your previous selection is no longer current. Review the changed requirements and supplier terms.</p>}
    {view&&!view.quotes.length&&<p role="status">{view.status==='no_enquiry'?'No supplier enquiry has been created for this case.':view.status==='awaiting_review'?'Supplier replies await operator review.':'Awaiting a supplier reply; silence is not acceptance.'}</p>}
    {view?.quotes.map(quote=><article key={quote.quote_id} data-testid={`buyer-supplier-quote-${quote.quote_id}`}>
      <strong>{quote.sku}: {quote.quantity} units ({quote.coverage})</strong>
      <p>Remaining shortfall: {quote.uncovered_quantity}. Minimum order: {quote.minimum_order}.</p>
      <p>Estimated lead time: {quote.estimated_lead_days} days. Expires: {quote.expires_at}.</p>
      {quote.requirement_assessment?.deadline_status==='estimate_late'&&<p>Estimated arrival misses your recorded deadline: {quote.requirement_assessment.required_by}.</p>}
      {quote.requirement_assessment?.deadline_status==='unresolved'&&<p>Clarify your delivery deadline before selecting this estimate.</p>}
      {quote.requirement_assessment?.deadline_status==='estimate_within_deadline'&&<p>Current estimated lead time fits your recorded deadline; delivery is not guaranteed.</p>}
      {quote.requirement_assessment?.budget_status==='unit_price_within_budget_freight_separate'&&<p>The unit price meets your budget. Freight is an additional disclosed charge.</p>}
      {quote.requirement_assessment?.budget_status==='covered_units_within_total_budget'&&<p>The estimate for covered units fits your total budget. Any uncovered units still need pricing.</p>}
      {quote.eligible&&quote.total_price_cents!==null?<><p>Supplier-sourced subtotal: {money(quote.total_price_cents,quote.currency)}, including freight {money(quote.freight_cents,quote.currency)}.</p>
        {quote.covered_order_total_price_cents!==null&&<p>Estimated total for {quote.covered_order_quantity} covered units, including local stock: {money(quote.covered_order_total_price_cents,quote.currency)}. Uncovered units are excluded.</p>}
        <button disabled={busy||selection?.status==='current'} onClick={()=>void select(quote)}>Select this sourcing estimate</button></>
        :<p>This option cannot currently be used: {quote.reason||quote.coverage}.</p>}
    </article>)}
  </section>;
}
