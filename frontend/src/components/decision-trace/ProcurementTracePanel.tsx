import type { ReactNode } from 'react';

type Props = {
  deliveryFeasibility?: any;
  fulfillmentEscalation?: any;
  classNames: Record<string, string>;
  humanize: (value: unknown) => string;
  children: ReactNode;
};

export default function ProcurementTracePanel({
  deliveryFeasibility,
  fulfillmentEscalation,
  classNames,
  humanize,
  children,
}: Props) {
  return (
    <section data-testid="procurement-trace-panel" className={classNames.summaryPane}>
      {deliveryFeasibility && (
        <div data-testid="trace-delivery-feasibility" className={classNames.anchorBlock}>
          <div className={classNames.sectionTitle}>Deadline Feasibility</div>
          <div className={classNames.kvRow}>
            <span>Requested window</span>
            <span>{deliveryFeasibility.delivery_window_days ?? deliveryFeasibility.horizon_days ?? '?'} day(s)</span>
          </div>
          <div className={classNames.kvRow}>
            <span>Verdict</span>
            <span>{humanize(String(deliveryFeasibility.feasibility || 'unknown'))}</span>
          </div>
          <div className={classNames.kvRow}>
            <span>Confirmed by deadline</span>
            <span>{deliveryFeasibility.quantity_confirmed_by_deadline ?? 0}</span>
          </div>
          <div className={classNames.kvRow}>
            <span>Quantity lacking dated arrival evidence</span>
            <span>{deliveryFeasibility.unknown_quantity ?? 'Not recorded'}</span>
          </div>
          {fulfillmentEscalation && (
            <div className={classNames.whyNarrative}>
              Human review: {humanize(String(
                fulfillmentEscalation.reason || fulfillmentEscalation.status || 'required'
              ))}. No supplier contact or delivery promise was executed.
            </div>
          )}
        </div>
      )}
      {children}
    </section>
  );
}
