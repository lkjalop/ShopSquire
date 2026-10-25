import {describe,expect,it} from 'vitest';
import {boundImageTriage,boundResearchOutcome,boundTurnProjection} from '../traceSnapshotBinding';
const snapshot={schema_version:'revision-bound-turn-read-model.v1',trace_id:'trace-one',case_id:'case-one',case_revision:2};
describe('trace snapshot binding',()=>{
  it('retains the exact trace and revision snapshot without granting authority',()=>{
    expect(boundTurnProjection(snapshot,'trace-one')).toBe(snapshot);
  });
  it.each([null,'trace-other'])('rejects an unbound or mismatched trace %s',trace=>{
    expect(boundTurnProjection(snapshot,trace)).toBeNull();
  });
  it.each([0,-1,2.5,'2',true,NaN])('rejects an invalid revision %s',case_revision=>{
    expect(boundTurnProjection({...snapshot,case_revision},'trace-one')).toBeNull();
  });
  it('rejects a missing case identity',()=>{
    expect(boundTurnProjection({...snapshot,case_id:' '},'trace-one')).toBeNull();
  });
  it('retains only the matching research case and revision',()=>{
    const outcome={schema_version:'research-outcome-v1',case_id:'case-one',case_revision:2};
    expect(boundResearchOutcome(outcome,snapshot)).toBe(outcome);
    expect(boundResearchOutcome({...outcome,case_id:'case-other'},snapshot)).toBeNull();
    expect(boundResearchOutcome({...outcome,case_revision:1},snapshot)).toBeNull();
    expect(boundResearchOutcome(outcome,null)).toBeNull();
  });
  it('keeps original inspection records only with their matching artifact trace',()=>{
    const owned={artifact:{artifact_id:'trace-one'},security:{artifact_state:'quarantined'}};
    const old={artifact:{artifact_id:'trace-old'},trace_id:'trace-one'};
    expect(boundImageTriage([owned,old,{security:{}}],'trace-one')).toEqual([owned]);
    expect(boundImageTriage([owned],null)).toEqual([owned]);
  });
});
