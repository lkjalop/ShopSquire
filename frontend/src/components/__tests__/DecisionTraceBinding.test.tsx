import {cleanup, render, screen, waitFor} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import DecisionTrace from '../DecisionTrace';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
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
