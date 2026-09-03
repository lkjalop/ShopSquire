import { useState } from 'react';
import {
  confirmOffCatalogSourcing,
  type OffCatalogSourcingOffer,
  type OffCatalogSourcingResult,
} from '../lib/api';

interface Props {
  offer: OffCatalogSourcingOffer;
  uid: string;
}

export default function OffCatalogSourcingCard({ offer, uid }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<OffCatalogSourcingResult | null>(null);
  const label = String(offer.subject_label || offer.label || 'this off-catalog item');

  const createDraft = async () => {
    setBusy(true);
    setError('');
    try {
      setResult(await confirmOffCatalogSourcing(uid, offer));
    } catch (err: any) {
      setError(String(err?.message || 'Could not create the sourcing request.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section data-testid="off-catalog-sourcing" className="fulfilment-options" aria-label="Off-catalog sourcing offer">
      <header><strong>Off-catalog sourcing</strong></header>
      <p>
        We do not stock <strong>{label}</strong>. You can create an internal sourcing request for review.
        This will not contact a supplier, place an order, or change your cart.
      </p>
      {error && <p role="alert" data-testid="off-catalog-sourcing-error">{error}</p>}
      {!result && (
        <button
          type="button"
          disabled={busy}
          onClick={createDraft}
          data-testid="create-sourcing-request"
        >
          {busy ? 'Creating draft…' : 'Create sourcing request'}
        </button>
      )}
      {result && (
        <div role="status" data-testid="off-catalog-sourcing-created">
          <p>
            Governed sourcing draft <strong>{result.case_id}</strong> created for case revision {result.case_revision}.
            No supplier has been contacted.
          </p>
          {result.draft?.rfq_preview_path && (
            <a href={result.draft.rfq_preview_path}>Open governed RFQ draft</a>
          )}
        </div>
      )}
    </section>
  );
}
