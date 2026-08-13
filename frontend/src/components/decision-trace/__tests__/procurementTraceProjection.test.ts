import { describe, expect, it } from 'vitest';

import {
  procurementQuarantineView,
  projectProcurementTraceView,
} from '../procurementTraceProjection';

describe('projectProcurementTraceView', () => {
  it('separates advisory projections from supplier and commerce authority', () => {
    const view = projectProcurementTraceView({
      events: [{
        event_type: 'market_intelligence_assessed',
        payload: { recommendation: 'ask for a dated quote' },
      }],
      procurementEvents: [{ event_type: 'supplier_responses_normalized' }],
      outboundIntegrityEvents: [{ event_type: 'outbound_integrity_blocked' }],
      procCase: {
        state_json: { draft: { subject: 'RFQ' }, procurement_trace: { quantity: 18 } },
        margin_advice: { deal_projection: { simulation_only: true } },
      },
      procJourney: [],
    });

    expect(view.marketIntelligence.recommendation).toBe('ask for a dated quote');
    expect(view.draft.subject).toBe('RFQ');
    expect(view.procurementTrace.quantity).toBe(18);
    expect(view.dealProjection.simulation_only).toBe(true);
    expect(view.authority).toBe('advisory_only');
    expect(view.supplierSendAuthority).toBe('none');
    expect(view.commerceAuthority).toBe('none');
  });

  it('projects quarantined supplier evidence without applying it', () => {
    const quarantine = procurementQuarantineView({
      state_json: {
        quarantine: {
          sender_domain: 'bad.example',
          reason: 'sender_untrusted',
          security: { severity: 'high', route: 'security_review', reasons: ['domain_mismatch'] },
        },
      },
    }, [{ event: 'supplier_response_quarantined', valid_from: '2026-08-13T01:02:03Z' }]);

    expect(quarantine).toMatchObject({
      active: true,
      senderDomain: 'bad.example',
      route: 'security_review',
      timestamp: '2026-08-13T01:02:03Z',
    });
  });
});
