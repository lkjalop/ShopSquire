export type CartMutationOp = {
  action: string;
  target_skus?: string[];
  quantity?: number;
  replacement_sku?: string;
  replacement_name?: string;
  budget_max_cents?: number;
  unit_price_cents?: number;
  previous_quantity?: number;
  allow_sourcing?: boolean;
};

export type PendingCartPlan = {
  planId: string;
  ops: CartMutationOp[];
  expiresAt?: string;
};

type CartLine = {
  sku?: string;
  name?: string;
  title?: string;
  quantity?: number;
  price?: number;
  price_cents?: number;
  currency?: string;
};

function money(cents: number, currency = 'AUD'): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: currency || 'AUD',
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function operationText(op: CartMutationOp, lines: CartLine[]): string {
  const target = String(op.target_skus?.[0] || '');
  const line = lines.find((item) => String(item.sku || '') === target);
  const name = String(line?.name || line?.title || target || 'cart line');
  const previous = Number.isFinite(Number(op.previous_quantity))
    ? Number(op.previous_quantity)
    : Number(line?.quantity || 0);
  const quantity = Number(op.quantity || 0);
  const unitCents = Number(op.unit_price_cents ?? line?.price_cents ?? (Number(line?.price || 0) * 100));
  const currency = String(line?.currency || 'AUD');

  if (op.action === 'set_quantity') {
    const delta = quantity - previous;
    const arithmetic = delta >= 0
      ? `${previous} + ${delta} = ${quantity}`
      : `${previous} - ${Math.abs(delta)} = ${quantity}`;
    const pricing = unitCents > 0
      ? ` · ${money(unitCents, currency)} × ${quantity} = ${money(unitCents * quantity, currency)}`
      : '';
    return `${name}: ${arithmetic} units${pricing}${op.allow_sourcing ? ' · stock shortfall may require supplier sourcing' : ''}`;
  }
  if (op.action === 'remove_items') {
    const total = unitCents > 0 && previous > 0 ? ` · −${money(unitCents * previous, currency)}` : '';
    return `${name}: ${previous || 'current'} → 0 units (remove line)${total}`;
  }
  if (op.action === 'clear_all') return 'Empty the whole cart';
  if (op.action === 'clear_previous') return 'Remove all carried-over lines and keep this session’s additions';
  if (op.action === 'keep_only') {
    return `Keep only ${(op.target_skus || []).join(', ') || 'the named lines'}; remove all others`;
  }
  if (op.action === 'replace_item') {
    return `${name}: replace with ${op.replacement_name || op.replacement_sku || 'the proposed product'} at ${quantity} units`;
  }
  return `${op.action}: ${(op.target_skus || []).join(', ') || 'cart'}`;
}

export default function PendingCartChangeCard({ plan, cartItems, onConfirm, onDismiss }: {
  plan: PendingCartPlan;
  cartItems?: CartLine[];
  onConfirm: () => void;
  onDismiss: () => void;
}) {
  const operations = Array.isArray(plan.ops) ? plan.ops : [];
  const expiry = plan.expiresAt ? new Date(plan.expiresAt.replace(' ', 'T')) : null;
  const expiryLabel = expiry && !Number.isNaN(expiry.getTime())
    ? expiry.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <section data-testid="pending-cart-change" style={{
      marginTop: 10,
      border: '1px solid #f59e0b',
      background: '#fffbeb',
      borderRadius: 10,
      padding: '10px 12px',
      color: '#78350f',
    }}>
      <div style={{ fontWeight: 700 }}>Pending cart change — nothing applied yet</div>
      <ol style={{ margin: '8px 0', paddingLeft: 22 }}>
        {operations.map((op, index) => (
          <li key={`${op.action}-${index}`} data-testid={`pending-cart-op-${index}`} style={{ marginBottom: 4 }}>
            {operationText(op, cartItems || [])}
          </li>
        ))}
      </ol>
      {expiryLabel && <div style={{ fontSize: 12, marginBottom: 8 }}>Confirmation expires at {expiryLabel}.</div>}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" onClick={onConfirm} style={{ fontWeight: 700 }}>
          Apply {operations.length > 1 ? `all ${operations.length} changes` : 'change'}
        </button>
        <button type="button" onClick={onDismiss}>Discard plan</button>
      </div>
    </section>
  );
}
