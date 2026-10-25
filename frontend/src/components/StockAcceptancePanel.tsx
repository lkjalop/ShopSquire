import {useEffect,useRef,useState} from 'react';
import {apiUrl,apiRequestHeaders} from '../lib/api';
import BuyerSupplierQuotes from './BuyerSupplierQuotes';
import CaseProductOffers from './CaseProductOffers';

type Stock={case_revision:number;available:number;sku:string;
  accepted:null|{requested_quantity:number;held_quantity:number;shortfall:number;hold_expires_at:string|null;shipped_quantity:number;returned_quantity:number}};

export default function StockAcceptancePanel({caseId,uid,revision,onAccepted,sku,initialQuantity=30}:{
  caseId:string;uid:string;revision?:number;onAccepted:(revision?:number)=>void;sku?:string;initialQuantity?:number;
}){
  const [stock,setStock]=useState<Stock|null>(null);
  const [quantity,setQuantity]=useState(initialQuantity);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const generation=useRef(0);
  useEffect(()=>{setQuantity(initialQuantity);},[initialQuantity]);
  const endpoint=sku ? `/api/v1/shopping-cases/${encodeURIComponent(caseId)}`
    : `/api/v1/demo/qualification-cases/${encodeURIComponent(caseId)}`;
  const headers=():Record<string,string>=>sku ? {} : {'X-Tenant-ID':'synthetic-electronics'};
  async function load(signal?:AbortSignal){
    const current=++generation.current;
    try{
      const response=await fetch(apiUrl(`${endpoint}/stock?uid=${encodeURIComponent(uid)}${sku?`&sku=${encodeURIComponent(sku)}`:''}`),{
        signal,credentials:'include',headers:apiRequestHeaders(headers())});
      if(!response.ok)throw new Error(`Stock unavailable (${response.status})`);
      const data=await response.json();
      if(current===generation.current){setStock(data);setError('');}
    }catch(reason){if(current===generation.current&&!signal?.aborted)setError(String(reason));}
  }
  useEffect(()=>{
    const controller=new AbortController();setStock(null);void load(controller.signal);
    return()=>{generation.current++;controller.abort();};
  },[endpoint,uid,revision,sku]);
  async function accept(release=false){
    if(!stock)return;
    setBusy(true);setError('');
    try{
      const response=await fetch(apiUrl(`${endpoint}/${release?'release-holds':'stock-acceptance'}`),{
        method:'POST',credentials:'include',headers:apiRequestHeaders(headers(),true),
        body:JSON.stringify({uid,expected_revision:stock.case_revision,
          ...(release?{}:{quantity,idempotency_key:crypto.randomUUID(),...(sku?{sku}:{})})}),
      });
      if(!response.ok)throw new Error(`Acceptance failed (${response.status}). Refresh stock before trying again.`);
      const receipt=await response.json();
      await load();onAccepted(receipt.case_revision);
    }catch(reason){setError(String(reason));}
    finally{setBusy(false);}
  }
  return <section aria-label="Simulated stock acceptance">
    <h2>Accept a simulated stock request</h2>
    <p data-testid="stock-case-reference">Case {caseId}{sku?` · SKU ${sku}`:''}</p>
    <p>This reserves fictional stock only. It does not place a purchase or send a supplier message. Changing quantity invalidates the previous qualification revision.</p>
    {stock&&<>
      <p>Live unreserved units: <span data-testid="live-available">{stock.available}</span></p>
      {stock.accepted&&<p data-testid="accepted-stock">Requested {stock.accepted.requested_quantity} · Held {stock.accepted.held_quantity} · Shortfall {stock.accepted.shortfall}</p>}
      {stock.accepted&&<p data-testid="stock-lifecycle">Shipped {stock.accepted.shipped_quantity||0} · Returned {stock.accepted.returned_quantity||0}</p>}
      {stock.accepted?.hold_expires_at&&<p data-testid="hold-expiry">Hold deadline: {stock.accepted.hold_expires_at}. Expired holds cannot be shipped; release or accept a fresh request to refresh stock.</p>}
      <label>Requested units <input type="number" min={1} max={10000} value={quantity} disabled={busy} onChange={e=>setQuantity(Number(e.target.value))}/></label>
      <button disabled={busy||!Number.isInteger(quantity)||quantity<1||quantity>10000} onClick={()=>void accept()}>Accept simulated stock request</button>
      <button disabled={busy||!(stock.accepted?.held_quantity||stock.accepted?.hold_expires_at)} onClick={()=>void accept(true)}>Release simulated holds</button>
    </>}
    <button disabled={busy} onClick={()=>void load()}>Refresh stock</button>
    {error&&<p role="alert">{error}</p>}
    {sku&&!stock?.accepted&&<CaseProductOffers caseId={caseId} uid={uid} sku={sku} revision={revision} onAccepted={onAccepted}/>}
    {stock?.accepted&&<BuyerSupplierQuotes caseId={caseId} uid={uid} revision={stock.case_revision}
      tenantId={sku?undefined:'synthetic-electronics'}/>}
  </section>;
}
