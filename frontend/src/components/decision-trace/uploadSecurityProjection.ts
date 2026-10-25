/** Presentation only: an upload verdict cannot invent recommendation authority. */
export function projectUploadSecurityFallback(trace:any,recommendation:any,imageTriage:any[]=[]){
  const items=Array.isArray(imageTriage) ? imageTriage : [];
  const triage=items[0] || {};
  const triageSec=triage.security && typeof triage.security==='object' ? triage.security : triage;
  const triageSignals=triageSec.signals && typeof triageSec.signals==='object' ? triageSec.signals : {};
  const imageSecurity=trace?.image_security || recommendation?.image_security || {};
  const matrix=trace?.right_panel?.security_matrix || recommendation?.right_panel_contract?.security_matrix || {};
  const state=String(triage.artifact?.state || triageSec.artifact_state || imageSecurity.trust_state || '').toLowerCase();
  if(!state && !Object.keys(triageSignals).length && !Object.keys(imageSecurity).length && !Object.keys(matrix).length)return null;
  const blocked=['received','admitted','pending','degraded','quarantined','superseded','under_review'].includes(state)
    || triage.artifact?.authority==='blocked' || triageSec.commercial_authority==='blocked';
  const recommendationAllowed=!blocked && state==='clean' && imageSecurity.recommendation_allowed===true;
  const deepPending=state==='pending' || triageSec.deferred_deep_analysis===true || triage.analysis_state?.analysis_pending===true;
  const rawQuarantined=typeof imageSecurity.raw_payload_quarantined==='boolean'
    ? imageSecurity.raw_payload_quarantined : state==='quarantined' ? true : null;
  const unsafeFlags=Array.isArray(imageSecurity.unsafe_flags) ? imageSecurity.unsafe_flags : [];
  const signals={...triageSignals,...Object.fromEntries(unsafeFlags.filter((flag:any)=>typeof flag==='string').map((flag:string)=>[flag,true])),
    raw_payload_quarantined:rawQuarantined,recommendation_allowed:recommendationAllowed,deep_security_pending:deepPending};
  const route=blocked ? 'block_commercial_authority' : matrix.policy_action || 'review_required';
  return {
    severity:triageSec.severity || imageSecurity.severity || (blocked ? 'review' : 'info'),
    policy_route:route,route,
    owasp_llm_top10:Array.isArray(matrix.owasp) ? matrix.owasp : [],
    mitre_atlas:Array.isArray(matrix.mitre) ? matrix.mitre : [],
    maestro:Array.isArray(matrix.maestro) ? matrix.maestro : [],
    signals,raw_payload_quarantined:rawQuarantined,recommendation_allowed:recommendationAllowed,
    deep_security_pending:deepPending,image_triage:items,image_security:imageSecurity,
  };
}
