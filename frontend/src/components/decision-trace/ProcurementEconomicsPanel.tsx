import { dealEconomicsStatus, formatDealMoney } from '../../lib/dealEconomicsDisplay';

export default function ProcurementEconomicsPanel({ deal, visible, classNames }: {
  deal: any; visible: boolean; classNames: Record<string, string>;
}) {
  if (!visible) return null;
  if (!deal) return <div data-testid="proc-deal-economics" style={{ border: '1px solid #f59e0b', background: '#fffbeb', borderRadius: 8, padding: '10px 12px', marginBottom: 12, fontSize: 13 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><strong>Deal economics unavailable</strong><span style={{ color: '#92400e', fontWeight: 700 }}>Evidence incomplete</span></div>
    <div style={{ color: '#4b5563', marginTop: 3 }}>Operator-only · supplier cost or comparable landed-cost evidence has not been validated</div>
    <div data-testid="proc-discount-authorization" style={{ marginTop: 7, padding: '6px 8px', borderRadius: 6, background: '#fef3c7', color: '#92400e', fontWeight: 600 }}>Discount authority locked until landed cost is validated</div>
  </div>;
  const status = dealEconomicsStatus(deal);
  return <div data-testid="proc-deal-economics" style={{ border: '1px solid #86efac', background: '#f0fdf4', borderRadius: 8, padding: '10px 12px', marginBottom: 12, fontSize: 13 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}><strong>{deal.simulation_only ? 'Scenario deal economics' : 'Live deal economics'}</strong><span style={{ color: deal.verdict === 'below_floor' ? '#b91c1c' : '#166534', fontWeight: 700 }}>{deal.simulation_only ? 'ESTIMATED · ' : ''}{status.verdict}</span></div>
    <div style={{ color: '#4b5563', marginTop: 3 }}>Operator-only · {status.costLabel}{deal.simulation_only ? ' · demo scenario' : ''}</div>
    <div className={classNames.kvRow}><span>List / unit</span><span>{formatDealMoney(deal.list_unit_cents, deal.currency)}</span></div>
    <div className={classNames.kvRow}><span>Supplier cost / unit</span><span>{formatDealMoney(deal.wholesale_unit_cents, deal.currency)}</span></div>
    <div className={classNames.kvRow}><span>Gross / unit</span><span>{formatDealMoney(deal.gross_per_unit_cents, deal.currency)}</span></div>
    <div className={classNames.kvRow}><span>List margin</span><span>{(Number(deal.margin_pct || 0) * 100).toFixed(1)}%</span></div>
    <div className={classNames.kvRow}><span>Projected gross ({Number(deal.quantity || 0)} units)</span><span>{formatDealMoney(deal.projected_profit_cents, deal.currency)}</span></div>
    <div data-testid="proc-discount-authorization" style={{ marginTop: 7, padding: '6px 8px', borderRadius: 6, background: deal.discount_authorized ? '#dcfce7' : '#fef3c7', color: deal.discount_authorized ? '#166534' : '#92400e', fontWeight: 600 }}>{status.discountLabel}</div>
    {Array.isArray(deal.bulk_breaks) && deal.bulk_breaks.length > 0 && <div style={{ marginTop: 8 }}><strong>Supplier volume scenarios</strong>{deal.bulk_breaks.map((tier: any) => <div key={`${tier.min_qty}-${tier.discount_pct}`} className={classNames.kvRow}><span>{tier.min_qty}+ units · {Number(tier.discount_pct || 0).toFixed(0)}% supplier break</span><span>{(Number(tier.margin_pct || 0) * 100).toFixed(1)}% estimated margin</span></div>)}<div style={{ color: '#6b7280', fontSize: 12 }}>Scenario only · not an authorized buyer discount or supplier commitment.</div></div>}
    <div style={{ borderTop: '1px dashed #86efac', marginTop: 8, paddingTop: 7, color: '#166534' }}>Model proposes · policy authorizes · connector executes · human approves supplier send</div>
  </div>;
}
