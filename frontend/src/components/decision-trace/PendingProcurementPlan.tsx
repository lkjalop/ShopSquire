type PendingLine = {
  sku: string;
  qty: number;
  eta_days?: number | null;
  supplier_ref?: string | null;
};

type PendingPlan = {
  split?: {
    now: PendingLine[];
    later: PendingLine[];
  };
  suppliers?: Record<string, {
    name?: string;
    channel?: string;
  }>;
};

type Props = {
  plan: PendingPlan;
};

function sumQuantity(lines: PendingLine[]): number {
  return lines.reduce((total, line) => total + line.qty, 0);
}

function channelLabel(channel: string): string {
  if (channel === 'email') return 'EMAIL — agent drafts, human sends';
  if (channel === 'phone') return 'PHONE — human-only';
  if (channel === 'portal') return 'PORTAL — human-only';
  return `${channel.toUpperCase()} — system integration`;
}

export default function PendingProcurementPlan({ plan }: Props) {
  if (!plan.split) return null;
  const grouped = plan.split.later.reduce<Record<string, PendingLine[]>>((result, line) => {
    const supplier = line.supplier_ref || 'unassigned';
    (result[supplier] ||= []).push(line);
    return result;
  }, {});

  return <div data-testid="proc-pending-plan" style={{ border: '1px solid #fcd34d', background: '#fffbeb', borderRadius: 10, padding: '10px 12px', fontSize: 13 }}>
    <div style={{ fontWeight: 700, marginBottom: 4 }}>Pending sourcing plan — nothing confirmed, no supplier contacted</div>
    <div style={{ color: '#92400e', marginBottom: 8 }}>
      {sumQuantity(plan.split.now)} ship from stock · {sumQuantity(plan.split.later)} require supplier reorder
    </div>
    {Object.entries(grouped).map(([supplierRef, lines]) => {
      const supplier = plan.suppliers?.[supplierRef] || {};
      const channel = String(supplier.channel || 'email').toLowerCase();
      const eta = Math.max(...lines.map((line) => line.eta_days ?? 0));
      return <div key={supplierRef} style={{ marginBottom: 8, paddingLeft: 6, borderLeft: '3px solid #f59e0b' }}>
        <div style={{ fontWeight: 600 }}>
          {supplier.name || supplierRef}{' '}
          <span style={{ fontWeight: 400, color: '#6b7280' }}>
            · {sumQuantity(lines)} unit(s){eta ? ` · ~${eta}d` : ''} · {channelLabel(channel)}
          </span>
        </div>
        {lines.map((line) => <div key={line.sku} style={{ color: '#374151' }}>{line.qty} × {line.sku}</div>)}
      </div>;
    })}
    <div style={{ color: '#6b7280' }}>
      RFQ drafts are created only after the buyer confirms the delivery plan (GATE 1). The trace then shows each human-gated draft and its audit history.
    </div>
  </div>;
}
