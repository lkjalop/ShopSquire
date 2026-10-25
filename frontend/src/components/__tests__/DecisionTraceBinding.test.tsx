import {cleanup, render, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import DecisionTrace from '../DecisionTrace';
import {clearOwnerApiKey,setOwnerApiKey} from '../../lib/browserSession';

beforeEach(() => {
  // This file models a buyer unless a test explicitly installs an operator key.
  // Hosted browser jobs also provide build keys for their separate operator UI.
  vi.stubEnv('VITE_API_KEY','');
  vi.stubEnv('VITE_OWNER_API_KEY','');
  clearOwnerApiKey();
});
afterEach(() => { cleanup(); clearOwnerApiKey(); vi.restoreAllMocks(); vi.unstubAllEnvs(); });
const projection = (trace: string, query: string) => ({
  schema_version:'revision-bound-turn-read-model.v1', trace_id:trace,
  case_id:'case-current', case_revision:2, buyer_query:query, products:[],
});
function stubTransport() {
  vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:false,status:403} as Response);
}
it('does not show another trace query as the requested decision', () => {
  stubTransport();
  render(<DecisionTrace traceId="trace-new" initialTab="summary" onClose={()=>{}}
    evidence={{turn_read_model:projection('trace-old','OLD PRIVATE QUERY')}} />);
  expect(screen.queryByText('OLD PRIVATE QUERY')).not.toBeInTheDocument();
});
it('updates the snapshot when the same trace receives a revised bound projection', async () => {
  stubTransport();
  const view=render(<DecisionTrace traceId="trace-current" initialTab="summary" onClose={()=>{}}
    evidence={{turn_read_model:projection('trace-current','FIRST QUERY')}} />);
  expect(screen.getByText('FIRST QUERY')).toBeInTheDocument();
  view.rerender(<DecisionTrace traceId="trace-current" initialTab="summary" onClose={()=>{}}
    evidence={{turn_read_model:{...projection('trace-current','AMENDED QUERY'),case_revision:3}}} />);
  await waitFor(()=>expect(screen.queryByText('FIRST QUERY')).not.toBeInTheDocument());
  expect(screen.getByText('AMENDED QUERY')).toBeInTheDocument();
});
it('does not attach an old image payload to a different requested trace', () => {
  stubTransport();
  render(<DecisionTrace traceId="trace-new" initialTab="security" onClose={()=>{}}
    imageTriage={[{artifact:{artifact_id:'trace-old',state:'quarantined',authority:'blocked'},
      security:{signals:{steg_suspicious:true,steg_details:{decoded_content:'OLD IMAGE PAYLOAD'}}}}]} />);
  expect(screen.queryByText(/OLD IMAGE PAYLOAD/)).not.toBeInTheDocument();
});
it('retains matching image inspection evidence while excluding a foreign artifact', () => {
  stubTransport();
  const triage=[{artifact:{artifact_id:'trace-owned',state:'quarantined',authority:'blocked'},
    security:{signals:{steg_suspicious:true,steg_details:{decoded_content:'INERT TEST'}}}}];
  const view=render(<DecisionTrace traceId="trace-owned" initialTab="security" onClose={()=>{}} imageTriage={triage} />);
  expect(screen.getByText('Decoded QR content or hidden payload content was inspected.')).toBeInTheDocument();
  view.rerender(<DecisionTrace traceId="trace-other" initialTab="security" onClose={()=>{}} imageTriage={triage} />);
  expect(screen.queryByText('Decoded QR content or hidden payload content was inspected.')).not.toBeInTheDocument();
});
it('uses a buyer snapshot without requesting operator-only trace endpoints', async () => {
  const request=vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:false,status:403} as Response);
  render(<DecisionTrace traceId="trace-current" initialTab="summary" onClose={()=>{}}
    evidence={{turn_read_model:projection('trace-current','OWNED BUYER QUERY')}} />);
  expect(screen.getByText('OWNED BUYER QUERY')).toBeInTheDocument();
  await waitFor(()=>expect(screen.getByTitle('Trace data source')).toHaveTextContent('snapshot'));
  expect(request.mock.calls.filter(([url])=>String(url).includes('/api/v1/decisions/'))).toHaveLength(0);
});
it('continues authenticated operator trace reads and treats rejection as terminal', async () => {
  setOwnerApiKey('test-only-operator-key');
  const request=vi.spyOn(globalThis,'fetch').mockResolvedValue({ok:false,status:403} as Response);
  render(<DecisionTrace traceId="trace-current" initialTab="security" onClose={()=>{}}
    evidence={{turn_read_model:projection('trace-current','OWNED QUERY')}} />);
  await waitFor(()=>expect(screen.getByText('auth',{exact:true})).toBeInTheDocument());
  const reads=request.mock.calls.filter(([url])=>String(url).includes('/api/v1/decisions/'));
  expect(reads).toHaveLength(1);
  expect(reads[0][1]?.headers).toEqual({'x-api-key':'test-only-operator-key'});
});
