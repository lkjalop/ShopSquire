import {test, expect} from './helpers/ordinaryBuyerTest';
import {resolve} from 'node:path';
import {readFileSync} from 'node:fs';

const corpus=process.env.SHOPSQUIRE_ADVERSARIAL_CORPUS;
test.skip(!corpus,'Original local clean-carrier profile must be explicitly selected');
for(const filename of ['apple-mac.jpg','lenovo-pro7.webp']){
  test(`clean carrier has completed steg inspection without an invented payload: ${filename}`,async({page},info)=>{
    const raw=readFileSync(resolve(corpus!,'../test-cv',filename));
    const response=await page.request.post('/api/v1/vision/triage',{
      params:{artifact_id:`clean-native-${filename}`},
      multipart:{image:{name:filename,mimeType:filename.endsWith('.jpg')?'image/jpeg':'image/webp',buffer:raw}},
    });
    expect(response.status()).toBe(200);
    const body=await response.json();
    expect(body.security.inspection_coverage.find((row:any)=>row.check==='steganography').status).toBe('pass');
    expect(body.security.signals.steg_suspicious).not.toBe(true);
    expect(body.security.payload_analysis.attack_hypothesis).toBe('unknown');
    expect(body.security.payload_findings).toEqual([]);
    await info.attach('clean-inspection-scope.json',{body:JSON.stringify({filename,
      state:body.artifact.state,coverage:body.security.inspection_coverage,
      hypothesis:body.security.payload_analysis.attack_hypothesis}),contentType:'application/json'});
  });
}
