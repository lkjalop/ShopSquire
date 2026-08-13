export type ProcurementQuarantineView = {
  active: boolean;
  senderDomain: string;
  reason: string;
  severity: string;
  route: string;
  securityReasons: string[];
  timestamp: string;
};

export type ProcurementTraceView = {
  events: any[];
  outboundIntegrityEvents: any[];
  marketIntelligence: any | null;
  draft: any | null;
  procurementTrace: any | null;
  dealProjection: any | null;
  quarantine: ProcurementQuarantineView;
  authority: 'advisory_only';
  supplierSendAuthority: 'none';
  commerceAuthority: 'none';
};

function originalEventType(event: any): string {
  return String(
    event?.payload?._original_event_type
    || event?.payload?.original_event_type
    || event?.event_type
    || '',
  ).toLowerCase().trim();
}

export function procurementQuarantineView(procCase: any, journey: any[]): ProcurementQuarantineView {
  const quarantine = procCase?.state_json?.quarantine;
  if (!quarantine || typeof quarantine !== 'object') {
    return {
      active: false,
      senderDomain: '',
      reason: '',
      severity: '',
      route: '',
      securityReasons: [],
      timestamp: '',
    };
  }
  const security = quarantine.security && typeof quarantine.security === 'object'
    ? quarantine.security
    : {};
  const transition = [...(Array.isArray(journey) ? journey : [])].reverse().find((item: any) => (
    String(item?.event || '').toLowerCase() === 'supplier_response_quarantined'
    || String(item?.state || '').toUpperCase() === 'SUPPLIER_RESPONSE_QUARANTINED'
  ));
  return {
    active: true,
    senderDomain: String(quarantine.sender_domain || 'not recorded'),
    reason: String(quarantine.reason || transition?.reason_code || 'security review required'),
    severity: String(security.severity || 'unknown'),
    route: String(security.route || 'security_review'),
    securityReasons: Array.isArray(security.reasons)
      ? security.reasons.map((value: any) => String(value)).filter(Boolean)
      : [],
    timestamp: String(transition?.valid_from || transition?.created_at || ''),
  };
}

export function projectProcurementTraceView({
  events,
  procurementEvents,
  outboundIntegrityEvents,
  procCase,
  procJourney,
}: {
  events: any[];
  procurementEvents: any[];
  outboundIntegrityEvents: any[];
  procCase: any;
  procJourney: any[];
}): ProcurementTraceView {
  const marketEvent = [...(events || [])].reverse().find((event: any) => (
    originalEventType(event) === 'market_intelligence_assessed'
    && event?.payload?.recommendation
  ));
  return {
    events: Array.isArray(procurementEvents) ? procurementEvents : [],
    outboundIntegrityEvents: Array.isArray(outboundIntegrityEvents) ? outboundIntegrityEvents : [],
    marketIntelligence: marketEvent?.payload || null,
    draft: procCase?.state_json?.draft || null,
    procurementTrace: procCase?.state_json?.procurement_trace || null,
    dealProjection: procCase?.margin_advice?.deal_projection || null,
    quarantine: procurementQuarantineView(procCase, procJourney || []),
    authority: 'advisory_only',
    supplierSendAuthority: 'none',
    commerceAuthority: 'none',
  };
}
