import {useEffect,useRef,useState} from 'react';
import {apiRequestHeaders,apiUrl} from '../lib/api';
import {getOrCreateStoredUid} from '../lib/browserSession';
import CaseContractSelection from './CaseContractSelection';
import StockAcceptancePanel from './StockAcceptancePanel';
import ProductShelvesPanel,{type ProductShelfProjection} from './ProductShelvesPanel';

type Result={simulation_only:boolean;case_revision:number;scenario_time:string;
  projection:ProductShelfProjection;trace:Record<string,unknown>};

export default function PortfolioQualification(){
  const [uid]=useState(getOrCreateStoredUid);
  const [caseId,setCaseId]=useState(new URLSearchParams(window.location.search).get('case_id')||'');
  const [expired,setExpired]=useState(false);
  const [result,setResult]=useState<Result|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [contractRefresh,setContractRefresh]=useState(0);
  const generation=useRef(0);
  async function refresh(){
    const current=++generation.current;
    setResult(null);setError('');
    if(!caseId)return;
    setBusy(true);
    try{
      const params=new URLSearchParams({uid,expired:String(expired)});
      const response=await fetch(apiUrl(`/api/v1/demo/qualification-cases/${encodeURIComponent(caseId)}?${params}`),{
        credentials:'include',headers:apiRequestHeaders({'X-Tenant-ID':'synthetic-electronics'})});
      if(!response.ok)throw new Error(`Qualification unavailable (${response.status})`);
      const data=await response.json();
      if(current===generation.current)setResult(data);
    }catch(reason){if(current===generation.current)setError(String(reason));}
    finally{if(current===generation.current)setBusy(false);}
  }
  useEffect(()=>{void refresh();return()=>{generation.current++;};},[caseId,expired]);
  async function start(){
    setBusy(true);setError('');
    try{
      const response=await fetch(apiUrl('/api/v1/demo/qualification-cases'),{
        method:'POST',credentials:'include',headers:apiRequestHeaders({'X-Tenant-ID':'synthetic-electronics'},true),body:JSON.stringify({uid})});
      if(!response.ok)throw new Error(`Case unavailable (${response.status})`);
      const data=await response.json();
      history.replaceState(null,'',`?surface=qualified-shop&case_id=${encodeURIComponent(data.case_id)}`);
      setCaseId(data.case_id);
    }catch(reason){setError(String(reason));setBusy(false);}
  }
  const products=result?.projection.shelves.flatMap(s=>[...s.initial,...s.next_page])||[];
  const qualified=products.length>0&&products.every(p=>p.fit_status==='qualified');
  return <main style={{maxWidth:1100,margin:'24px auto',padding:24}}>
    <h1>Fictional shop qualification</h1>
    <p>This fixed-clock simulation checks RAM capacity only. Invented evidence does not certify any real product or application.</p>
    {!caseId&&<button disabled={busy} onClick={()=>void start()}>Start fictional buyer case</button>}
    {caseId&&<>
      <CaseContractSelection key={contractRefresh} caseId={caseId} uid={uid} tenantId="synthetic-electronics" onChange={()=>void refresh()}/>
      <StockAcceptancePanel caseId={caseId} uid={uid} revision={result?.case_revision}
        onAccepted={()=>{setContractRefresh(value=>value+1);void refresh();}}/>
      <label><input type="checkbox" checked={expired} disabled={busy} onChange={e=>setExpired(e.target.checked)}/> Replay expired evidence</label>
      {result&&<>
        <h2 data-testid="qualification-status">{qualified?'Qualified for fictional scope':'Not qualified'}</h2>
        <p>Case revision {result.case_revision} · Scenario clock {result.scenario_time} · Commerce authority none</p>
        <ProductShelvesPanel projection={result.projection}/>
        <details><summary>Qualification trace</summary><pre data-testid="qualification-trace" style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(result.trace,null,2)}</pre></details>
      </>}
    </>}
    {busy&&<p role="status">Checking evidence…</p>}
    {error&&<p role="alert">{error}</p>}
  </main>;
}
