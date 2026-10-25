import {expect,it} from 'vitest';
import {projectUploadSecurityFallback as project} from '../uploadSecurityProjection';

it.each(['pending','quarantined','degraded','superseded'])('a %s upload overrides an optimistic route and signal',state=>{
  const result=project({image_security:{recommendation_allowed:true,unsafe_flags:['recommendation_allowed']},
    right_panel:{security_matrix:{policy_action:'allow_recommendation'}}},null,
    [{artifact:{state,authority:'blocked'},security:{signals:{recommendation_allowed:true}}}])!;
  expect(result.recommendation_allowed).toBe(false);
  expect(result.signals.recommendation_allowed).toBe(false);
  expect(result.policy_route).toBe('block_commercial_authority');
});

it('retains explicit read-only recommendation permission only for a clean artifact',()=>{
  const result=project({image_security:{recommendation_allowed:true}},null,[{artifact:{state:'clean'}}])!;
  expect(result.recommendation_allowed).toBe(true);
});

it('neither invents permission for a clean image nor pending work for a final quarantine',()=>{
  expect(project(null,null,[{artifact:{state:'clean'}}])!.recommendation_allowed).toBe(false);
  expect(project(null,null,[{artifact:{state:'quarantined'}}])!.deep_security_pending).toBe(false);
});

it('returns no invented inspection when its inputs are absent',()=>{
  expect(project(null,null)).toBeNull();
  expect(project(null,null,null as any)).toBeNull();
});
