import React, { useState } from 'react';
import { apiFetch } from '../lib/csrf';
import { getOwnerApiKey } from '../lib/browserSession';

export default function InventoryOperationsPanel() {
  const [tenant,setTenant]=useState('');
  const [sku,setSku]=useState('');
  const [kind,setKind]=useState('receive');
  const [source,setSource]=useState('');
  const [destination,setDestination]=useState('');
  const [reference,setReference]=useState('');
  const [quantity,setQuantity]=useState(1);
  const [reservation,setReservation]=useState('');
  const [caseId,setCaseId]=useState('');
  const [revision,setRevision]=useState(1);
  const [requestId,setRequestId]=useState('');
  const [record,setRecord]=useState<any>(null);
  const [stock,setStock]=useState<any>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const headers=()=>({'x-api-key':getOwnerApiKey(),'x-tenant-id':tenant.trim()});
  const lifecycle=['ship','cancel','return'].includes(kind);
  async function perform(action:string){
    setBusy(true);setError('');
    try{
      const base='/api/v1/admin/inventory/operations';
      if(action==='create'){
        const row=await apiFetch<any>(base,{method:'POST',headers:headers(),body:JSON.stringify({
          kind,sku:sku.trim(),source_reference:reference.trim(),quantity,
          destination_location:lifecycle?null:destination.trim(),source_location:kind==='transfer'?source.trim():null,
          ...(lifecycle?{reservation_id:reservation,case_id:caseId,case_revision:revision}:{})})});
        setRecord(row);setRequestId(row.id);
      }else if(action==='stock'){
        setStock(await apiFetch(`/api/v1/admin/inventory/operation-stock/${encodeURIComponent(sku.trim())}`,{headers:headers()}));
      }else{
        if(action!=='load')await apiFetch(`${base}/${encodeURIComponent(requestId)}/${action}`,{method:'POST',headers:headers()});
        const row=await apiFetch<any>(`${base}/${encodeURIComponent(requestId)}`,{headers:headers()});
        setRecord(row);setSku(row.payload.sku);
        setStock(await apiFetch(`/api/v1/admin/inventory/operation-stock/${encodeURIComponent(row.payload.sku)}`,{headers:headers()}));
      }
    }catch(e){
      const message=e instanceof Error?e.message:'Operation unavailable';
      setError(message.includes('distinct_people_required')?'A different enrolled person must approve this request.':message);
    }finally{setBusy(false);}
  }
  return <section aria-label="Inventory operations" style={{padding:20}}>
    <h3>Inventory operations</h3>
    <p>Fictional shop only. A different enrolled person must approve each inventory action before stock changes. Shipping and returns use the accepted buyer reservation and current case revision.</p>
    <label>Tenant <input aria-label="Inventory tenant" value={tenant} disabled={busy} onChange={e=>{setTenant(e.target.value);setRecord(null);setStock(null);}}/></label>{' '}
    <label>SKU <input aria-label="Inventory SKU" value={sku} disabled={busy} onChange={e=>{setSku(e.target.value);setRecord(null);setStock(null);}}/></label>{' '}
    <button disabled={busy||!tenant||!sku} onClick={()=>perform('stock')}>Refresh stock</button>
    <fieldset disabled={busy}>
      <legend>Request a stock movement</legend>
      <label>Operation <select aria-label="Inventory operation" value={kind} onChange={e=>setKind(e.target.value)}><option value="receive">Receive delivery</option><option value="transfer">Transfer stock</option><option value="ship">Ship accepted hold</option><option value="cancel">Cancel accepted hold</option><option value="return">Receive returned units</option></select></label>{' '}
      {kind==='transfer'&&<label>From <input aria-label="Source location" value={source} onChange={e=>setSource(e.target.value)}/></label>}{' '}
      {!lifecycle&&<label>To <input aria-label="Destination location" value={destination} onChange={e=>setDestination(e.target.value)}/></label>}{' '}
      {lifecycle&&<><label>Reservation <input aria-label="Reservation ID" value={reservation} onChange={e=>setReservation(e.target.value)}/></label>{' '}
        <label>Buyer case <input aria-label="Inventory case ID" value={caseId} onChange={e=>setCaseId(e.target.value)}/></label>{' '}
        <label>Case revision <input aria-label="Inventory case revision" type="number" min="1" value={revision} onChange={e=>setRevision(Number(e.target.value))}/></label></>}
      <label>Quantity <input aria-label="Movement quantity" type="number" min="1" max="10000" value={quantity} onChange={e=>setQuantity(Number(e.target.value))}/></label>{' '}
      <label>Document reference <input aria-label="Movement reference" value={reference} onChange={e=>setReference(e.target.value)}/></label>{' '}
      <button disabled={!tenant||!sku||!(lifecycle?reservation&&caseId:destination)||!reference} onClick={()=>perform('create')}>Request movement</button>
    </fieldset>
    <label>Request ID <input aria-label="Inventory request ID" value={requestId} disabled={busy} onChange={e=>{setRequestId(e.target.value);setRecord(null);}}/></label>{' '}
    <button disabled={busy||!requestId||!tenant} onClick={()=>perform('load')}>Load request</button>{' '}
    <button disabled={busy||record?.status!=='pending'} onClick={()=>perform('approve')}>Approve movement</button>{' '}
    <button disabled={busy||record?.status!=='approved'} onClick={()=>perform('execute')}>Execute approved movement</button>
    {error&&<p role="alert">{error}</p>}
    {record&&<div role="status"><p>Request {record.id} · {record.status}</p>
      <p>Server-calculated inventory value: {record.currency} {(record.value_cents/100).toFixed(2)}</p>
      <p>{record.payload.kind}: {record.payload.quantity} units of {record.payload.sku}{record.payload.destination_location?` to ${record.payload.destination_location}`:` for reservation ${record.payload.reservation_id}, case revision ${record.payload.case_revision}`}.</p>
    </div>}
    {stock&&<><p>Stock reconciled: {stock.reconciliation?.consistent===true?'yes':'not established'}. Recorded movements: {stock.movement_count}.</p>
      <table><thead><tr><th>Location</th><th>On hand</th><th>Reserved</th><th>Available</th></tr></thead>
        <tbody>{stock.locations.map((row:any)=><tr key={row.location_id}><td>{row.location_id}</td><td>{row.on_hand}</td><td>{row.reserved}</td><td>{row.available}</td></tr>)}</tbody></table>
      <p>Recorded reservation events: {stock.reservation_event_count}</p>
      <details><summary>Accepted stock reservations</summary><ul>{(stock.reservations||[]).map((row:any)=><li key={row.reservation_id}>
        {row.reservation_id}: {row.quantity} units, {row.status}, {row.returned_quantity} returned. Case {row.case_id||'unbound'}, revision {row.case_revision||'unknown'}.
        {row.case_id&&<button onClick={()=>{setReservation(row.reservation_id);setCaseId(row.case_id);setRevision(row.case_revision);setQuantity(row.quantity);setKind('ship');}}>Use this reservation</button>}
      </li>)}</ul></details></>}
  </section>;
}
