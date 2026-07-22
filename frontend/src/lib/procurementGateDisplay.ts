export type ProcurementGateDisplay = {
  label: string;
  reasons: { code: string; label: string; action: string }[];
};

export function procurementDraftPending(procCase: unknown): boolean {
  if (!procCase || typeof procCase !== 'object') return false;
  const record = procCase as Record<string, any>;
  return String(record.state || '').toUpperCase() === 'COMMITTED'
    && !record.state_json?.draft;
}

const REASON_COPY: Record<string, { label: string; action: string }> = {
  below_supplier_moq: {
    label: 'Supplier minimum quantity is not met.',
    action: 'Consolidate demand, raise the RFQ quantity with approval, or select another qualified supplier.',
  },
  missing_required_by: {
    label: 'A concrete required-by date is missing.',
    action: 'Capture the buyer delivery date before the draft is approved.',
  },
  missing_required_rfq_fields: {
    label: 'Required RFQ details are incomplete.',
    action: 'Complete the highlighted commercial fields before approval.',
  },
  missing_commercial_scope: {
    label: 'The item or sourced quantity is missing.',
    action: 'Rebuild the draft from the current cart and sourcing shortfall.',
  },
  low_confidence: {
    label: 'Draft confidence is below policy.',
    action: 'Review the supplier, product identity, quantity, and supporting evidence.',
  },
  no_evidence: {
    label: 'No supporting evidence was attached.',
    action: 'Refresh inventory, supplier terms, and scoped market evidence.',
  },
  no_recipient: {
    label: 'No approved supplier recipient is resolved.',
    action: 'Select an allowlisted supplier contact.',
  },
  claim_unsafe: {
    label: 'The outbound integrity policy blocked the draft.',
    action: 'Remove unsafe claims or data and regenerate the draft.',
  },
};

function reasonCopy(code: string): { label: string; action: string } | undefined {
  if (code.startsWith('missing_rfq_fields:')) {
    const fields = code.slice('missing_rfq_fields:'.length).split(',').filter(Boolean).join(', ');
    return {
      label: `Required RFQ field${fields.includes(',') ? 's are' : ' is'} missing: ${fields}.`,
      action: fields.includes('deadline_date')
        ? 'Capture a concrete required-by date before the draft is approved.'
        : 'Complete the missing commercial fields before approval.',
    };
  }
  return REASON_COPY[code];
}

export function procurementGateDisplay(gate: unknown): ProcurementGateDisplay {
  if (!gate) return { label: '', reasons: [] };
  if (typeof gate === 'string') return { label: gate, reasons: [] };
  if (typeof gate !== 'object') return { label: String(gate), reasons: [] };
  const record = gate as Record<string, unknown>;
  const decision = String(record.decision || record.status || record.action || 'recorded');
  const blocking = Array.isArray(record.blocking) ? record.blocking.map(String) : [];
  const needs = Array.isArray(record.reasons) ? record.reasons.map(String) : [];
  const codes = [...new Set([...blocking, ...needs])];
  return {
    label: `${decision}${blocking.length ? ` - ${blocking.length} blocker${blocking.length === 1 ? '' : 's'}` : ''}`,
    reasons: codes.map((code) => {
      const copy = reasonCopy(code);
      return {
        code,
        label: copy?.label || code.replace(/_/g, ' '),
        action: copy?.action || 'Review and resolve this policy condition before approval.',
      };
    }),
  };
}
