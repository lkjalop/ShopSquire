import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,describe,expect,it} from 'vitest';
import DecisionTrace from '../DecisionTrace';

afterEach(cleanup);
function renderRecoveredPayload(){
  render(<DecisionTrace traceId={null} initialTab="security" onClose={()=>undefined} imageTriage={[{
    _filename:'inert-beacon.png',artifact:{state:'quarantined',authority:'blocked'},
    security:{artifact_state:'quarantined',commercial_authority:'blocked',
      signals:{steg_suspicious:true,steg_details:{decoded_content:'{"type":"TEST_BEACON","interval":300}'}},
      payload_analysis:{payload_type:'steg_decoded_payload',attack_hypothesis:'c2_beacon',
        claim_status:'possible',runtime_confirmation_required:true},
      payload_findings:[{finding_type:'c2_beacon_pattern',headline:'Hidden C2 beacon pattern detected',
        business_risk:'Review the decoded pattern before drawing conclusions.'}]},
  }]} />);
}

describe('security explanations preserve the evidence level',()=>{
  it('does not mislabel severity as measured confidence',()=>{
    renderRecoveredPayload();
    expect(screen.queryByText(/(?:info|review|high|low) confidence/i)).not.toBeInTheDocument();
  });
  it('does not promote a decoded callback pattern into observed runtime behavior',()=>{
    renderRecoveredPayload();
    expect(screen.queryByText(/Hidden beacon or callback behavior was detected/i)).not.toBeInTheDocument();
  });
  it('acknowledges recovered LSB content even when no QR is present',()=>{
    renderRecoveredPayload();
    expect(screen.queryByText('No direct QR or hidden payload content was observed.')).not.toBeInTheDocument();
    expect(screen.getByText('Decoded QR content or hidden payload content was inspected.')).toBeInTheDocument();
  });
  it('never turns a quarantined inspection into an allow-recommendation policy',()=>{
    renderRecoveredPayload();
    const row=screen.getByText('Policy Route').parentElement!;
    expect(row.textContent).not.toMatch(/allow.recommendation/i);
  });
});
