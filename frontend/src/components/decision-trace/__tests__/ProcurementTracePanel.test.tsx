import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ProcurementTracePanel from '../ProcurementTracePanel';


describe('ProcurementTracePanel', () => {
  it('keeps deadline evidence and human escalation non-authoritative', () => {
    render(
      <ProcurementTracePanel
        deliveryFeasibility={{
          delivery_window_days: 10,
          feasibility: 'partial',
          quantity_confirmed_by_deadline: 12,
          unknown_quantity: 18,
        }}
        fulfillmentEscalation={{ reason: 'supplier_confirmation_required' }}
        classNames={{ summaryPane: 'summary', anchorBlock: 'anchor', sectionTitle: 'title', kvRow: 'kv', whyNarrative: 'why' }}
        humanize={(value) => String(value).replaceAll('_', ' ')}
      >
        <div>Typed supplier continuation</div>
      </ProcurementTracePanel>,
    );

    const panel = screen.getByTestId('procurement-trace-panel');
    expect(panel).toHaveTextContent(/12/);
    expect(panel).toHaveTextContent(/18/);
    expect(panel).toHaveTextContent(/No supplier contact or delivery promise was executed/i);
    expect(panel).toHaveTextContent(/Typed supplier continuation/i);
  });
});
