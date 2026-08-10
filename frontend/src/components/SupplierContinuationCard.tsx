export type FulfillmentChoice = {
  choice_id: string;
  label: string;
  available_now: number;
  remaining: number;
};

export type SupplierOffer = {
  offer_id: string;
  offered_sku: string;
  relationship: 'exact' | 'compatible_substitute';
  quantity_available: number;
  lead_time_days?: number | null;
  unit_price_cents?: number | null;
  currency?: string;
  validity_expires_at?: string | null;
  provenance?: Record<string, string>;
  supplier_send?: string;
  purchase_commitment?: boolean;
  response_status?: 'accepted' | 'rejected' | 'conditional' | 'late' | 'unverified';
  response_reason?: string;
};

export type SupplierContinuation = {
  caseId: string;
  preferredSku: string;
  preferredTitle: string;
  substituteSku?: string;
  requestedQuantity: number;
  unitPriceCents: number;
  currency: string;
  availableNow: number | null;
  deadlineDays: number;
  choices: FulfillmentChoice[];
  selectedChoice?: string;
  selectionId?: string;
  revision?: number;
  offers?: SupplierOffer[];
  selectedOfferId?: string;
  selectionKey: string;
  confirmationKey: string;
  status?: 'review' | 'selecting' | 'offers' | 'confirming' | 'applied';
  error?: string;
  proportionateAlternatives?: import('../lib/proportionateAlternatives').ProportionateAlternative[];
};

const actionStyle = {
  border: '1px solid #f15a0a', borderRadius: 7, padding: '7px 10px',
  background: '#fff', color: '#c2410c', fontWeight: 700, cursor: 'pointer',
} as const;

const HIGH_VALUE_TOTAL_CENTS = 3_000_000;
const HIGH_VALUE_QUANTITY = 10;
const HIGH_VALUE_UNIT_PRICE_CENTS = 400_000;

export function commercialReviewReasons(journey: Pick<SupplierContinuation,
  'requestedQuantity' | 'unitPriceCents' | 'currency'>): string[] {
  if ((journey.currency || 'AUD').toUpperCase() !== 'AUD') return [];
  const reasons: string[] = [];
  if (journey.unitPriceCents * journey.requestedQuantity >= HIGH_VALUE_TOTAL_CENTS) {
    reasons.push('Total value is at least AUD 30,000.');
  }
  if (journey.requestedQuantity > HIGH_VALUE_QUANTITY
    && journey.unitPriceCents >= HIGH_VALUE_UNIT_PRICE_CENTS) {
    reasons.push('Quantity is over 10 and unit price is at least AUD 4,000.');
  }
  return reasons;
}

export default function SupplierContinuationCard({ journey, onAssess, onSelectChoice, onSelectOffer, onConfirm, onBack, onDismiss }: {
  journey: SupplierContinuation;
  onAssess: (deadlineDays: number) => void;
  onSelectChoice: (choiceId: string) => void;
  onSelectOffer: (offerId: string) => void;
  onConfirm: () => void;
  onBack: () => void;
  onDismiss: () => void;
}) {
  const shortfall = journey.availableNow == null
    ? null : Math.max(0, journey.requestedQuantity - journey.availableNow);
  const chosenOffer = journey.offers?.find((offer) => offer.offer_id === journey.selectedOfferId);
  const needsOffer = ['supplier_enquiry', 'substitute', 'next_best_now'].includes(String(journey.selectedChoice));
  const readyToConfirm = Boolean(journey.selectionId && (!needsOffer || chosenOffer));
  const commercialReview = commercialReviewReasons(journey);

  return (
    <section data-testid="supplier-continuation" style={{
      margin: '0 12px 14px', border: '1px solid #fdba74', borderRadius: 10,
      background: '#fff7ed', padding: 12, color: '#431407',
    }}>
      <strong>Fulfilment review — nothing has changed yet</strong>
      <div style={{ marginTop: 5 }}>
        {journey.requestedQuantity} × {journey.preferredTitle}
      </div>
      <div style={{ marginTop: 4, fontWeight: 700 }}>
        Estimated catalogue value: {new Intl.NumberFormat('en-AU', {
          style: 'currency', currency: journey.currency || 'AUD', maximumFractionDigits: 0,
        }).format((journey.unitPriceCents * journey.requestedQuantity) / 100)}
      </div>
      {commercialReview.length > 0 && (
        <div data-testid="high-value-order-warning" style={{
          color: '#9a3412', fontSize: 12, marginTop: 6, borderLeft: '3px solid #f15a0a', paddingLeft: 8,
        }}>
          <strong>Commercial review</strong>
          <div>Threshold: triggered</div>
          <div>Reason:</div>
          <ul style={{ margin: '2px 0 2px 18px', padding: 0 }}>
            {commercialReview.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
          <div>Resolution owner: tenant policy / human</div>
          <div>Portfolio enforcement: advisory only</div>
          <div>Purchase authority: unchanged</div>
        </div>
      )}
      {commercialReview.length > 0 && journey.proportionateAlternatives?.length ? (
        <section data-testid="proportionate-alternatives" style={{ marginTop: 9 }}>
          <strong>Commercially proportionate alternatives</strong>
          <div style={{ fontSize: 12, marginTop: 2 }}>
            The preferred technical fit remains selected. These options reduce unit cost by at least 20% without a verified minimum failure.
          </div>
          <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
            {journey.proportionateAlternatives.map((alternative) => (
              <div key={alternative.sku} style={{ border: '1px solid #fed7aa', borderRadius: 7, background: '#fff', padding: 7 }}>
                <strong>{alternative.title}</strong>
                <div style={{ fontSize: 12 }}>
                  {new Intl.NumberFormat('en-AU', { style: 'currency', currency: alternative.currency, maximumFractionDigits: 0 }).format(alternative.priceCents / 100)}
                  {' · '}{alternative.savingsPercent}% lower ({new Intl.NumberFormat('en-AU', { style: 'currency', currency: alternative.currency, maximumFractionDigits: 0 }).format(alternative.savingsCents / 100)} saved per unit)
                </div>
                <div style={{ fontSize: 11 }}>{alternative.compromise}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      <div style={{ fontSize: 12, marginTop: 4 }}>
        {journey.availableNow == null
          ? 'Verified numeric availability is unknown.'
          : `${journey.availableNow} verified now · ${shortfall} require another fulfilment path.`}
      </div>

      {!journey.choices.length && (
        <div style={{ display: 'flex', gap: 7, alignItems: 'center', marginTop: 10 }}>
          <label htmlFor="supplier-deadline">Needed within</label>
          <input id="supplier-deadline" aria-label="Needed within days" type="number" min={1} max={365}
            defaultValue={journey.deadlineDays} style={{ width: 62 }} />
          <span>days</span>
          <button type="button" style={actionStyle} onClick={() => {
            const input = document.getElementById('supplier-deadline') as HTMLInputElement | null;
            onAssess(Math.max(1, Number(input?.value || journey.deadlineDays)));
          }}>Assess fulfilment</button>
        </div>
      )}

      {journey.choices.length > 0 && !journey.selectionId && (
        <div data-testid="fulfillment-choices" style={{ display: 'grid', gap: 7, marginTop: 10 }}>
          {journey.choices.slice(0, 6).map((choice) => (
            <button key={choice.choice_id} type="button" style={{ ...actionStyle, textAlign: 'left' }}
              disabled={journey.status === 'selecting'}
              onClick={() => onSelectChoice(choice.choice_id)}>{choice.label}</button>
          ))}
        </div>
      )}

      {journey.offers?.length ? (
        <div data-testid="supplier-offers" style={{ display: 'grid', gap: 7, marginTop: 10 }}>
          <strong>Synthetic certification responses</strong>
          {journey.offers.map((offer) => (
            <label key={offer.offer_id} style={{
              display: 'block', border: '1px solid #fed7aa', borderRadius: 7,
              padding: 8, background: offer.quantity_available > 0 ? '#fff' : '#f8fafc',
            }}>
              <input type="radio" name="supplier-offer" disabled={offer.quantity_available === 0}
                checked={journey.selectedOfferId === offer.offer_id}
                onChange={() => onSelectOffer(offer.offer_id)} />{' '}
              {offer.quantity_available > 0
                ? `${offer.quantity_available} × ${offer.offered_sku}${offer.lead_time_days == null ? '' : ` in ${offer.lead_time_days} days`}`
                : `${offer.offered_sku}: unable to fulfil`}
              {offer.relationship === 'compatible_substitute' ? ' · proposed substitute' : ' · exact configuration'}
              {offer.relationship === 'compatible_substitute' ? ' · workload fit remains conditional until all unknowns are resolved' : ''}
              <div style={{
                marginTop: 3, fontSize: 11, fontWeight: 700,
                color: offer.response_status === 'accepted' ? '#047857'
                  : offer.response_status === 'rejected' ? '#991b1b' : '#92400e',
              }}>
                {String(offer.response_status || 'unverified').toUpperCase()}
                {offer.response_reason ? ` — ${offer.response_reason}` : ''}
              </div>
              {offer.response_status === 'accepted'
                && offer.relationship === 'exact'
                && (journey.availableNow || 0) + offer.quantity_available >= journey.requestedQuantity ? (
                  <div style={{ fontSize: 11 }}>Preferred fit — completes the requested quantity by the deadline.</div>
                ) : offer.response_status === 'conditional'
                  && offer.relationship === 'compatible_substitute'
                  && offer.quantity_available >= journey.requestedQuantity ? (
                    <div style={{ fontSize: 11 }}>Next-best complete order — conditional substitute.</div>
                  ) : offer.response_status === 'late' ? (
                    <div style={{ fontSize: 11 }}>Preferred fit — misses the requested deadline.</div>
                  ) : null}
              <details style={{ marginTop: 4, fontSize: 11 }}>
                <summary>Evidence and supplier-response details</summary>
                <div>Fixture only — no supplier was contacted and this is not a purchase commitment.</div>
                <div>Source: {offer.provenance?.supplier_reference || 'not recorded'}</div>
                <div>Validity: {offer.validity_expires_at || 'not recorded'}</div>
              </details>
            </label>
          ))}
        </div>
      ) : null}

      <details style={{ marginTop: 10, fontSize: 12 }}>
        <summary>Real supplier mode</summary>
        <div data-testid="real-supplier-locked" style={{ marginTop: 5 }}>
          Locked for this portfolio profile. A verified supplier identity, approved credentials,
          human RFQ preview and explicit send authorization are required.
        </div>
      </details>

      {journey.selectionId && (
        <div style={{ marginTop: 10, borderTop: '1px solid #fed7aa', paddingTop: 9 }}>
          <strong>Final confirmation</strong>
          <div style={{ fontSize: 12, margin: '4px 0 8px' }}>
            {chosenOffer?.relationship === 'compatible_substitute'
              ? `Use ${chosenOffer.offered_sku} as an explicitly accepted, conditional-fit substitute for all ${journey.requestedQuantity} units.`
              : chosenOffer && journey.availableNow != null
                ? `${journey.availableNow} × ${journey.preferredSku} available now + ${chosenOffer.quantity_available} supplier-confirmed${chosenOffer.lead_time_days == null ? '' : ` in ${chosenOffer.lead_time_days} days`}.`
                : `Keep ${journey.preferredSku} for all ${journey.requestedQuantity} units using the selected fulfilment path.`}
          </div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            Total at catalogue price: {new Intl.NumberFormat('en-AU', {
              style: 'currency', currency: journey.currency || 'AUD', maximumFractionDigits: 0,
            }).format((journey.unitPriceCents * journey.requestedQuantity) / 100)}
            {' · '}Commercial review: advisory
            {' · '}Supplier enquiry: not a purchase commitment
          </div>
          <button type="button" style={{ ...actionStyle, background: '#f15a0a', color: '#fff' }}
            disabled={!readyToConfirm || journey.status === 'confirming' || journey.status === 'applied'}
            onClick={onConfirm}>
            {journey.status === 'applied' ? 'Cart updated' : 'Confirm exact cart change'}
          </button>
          {journey.status !== 'applied' && (
            <button type="button" style={{ ...actionStyle, marginLeft: 7 }} onClick={onBack}>
              Change fulfilment choice
            </button>
          )}
        </div>
      )}
      {journey.error && <div role="alert" style={{ color: '#991b1b', marginTop: 8 }}>{journey.error}</div>}
      <button type="button" onClick={onDismiss} style={{ ...actionStyle, marginTop: 10 }}>Close review</button>
    </section>
  );
}
