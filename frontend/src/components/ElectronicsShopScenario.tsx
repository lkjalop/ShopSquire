import { useState } from 'react';
import { apiUrl } from '../lib/api';
import styles from './ProcurementCertificationShowcase.module.css';

type Assessment = {
  sku: string; available: number; shortfall: number; request_digest: string;
  retail_total_cents: number | null;
  supplier_offers: Array<{supplier_id: string; order_quantity: number; unit_cost_cents: number;
    order_cost_cents: number; available_now: number; later_quantity: number; later_arrival: string; uncovered_shortfall: number}>;
};
type History = {
  events: Array<{sequence:number;location_id:string;kind:string;quantity:number}>;
  locations: Array<{location_id:string;on_hand:number;reserved:number;available:number}>;
};

export default function ElectronicsShopScenario() {
  const [quantity, setQuantity] = useState('30');
  const [sku, setSku] = useState('');
  const [skus, setSkus] = useState<string[]>([]);
  const [result, setResult] = useState<Assessment | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [time, setTime] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function assess() {
    setBusy(true); setError(''); setResult(null); setHistory(null);
    try {
      const params = new URLSearchParams({quantity});
      if (sku) params.set('sku', sku);
      const response = await fetch(apiUrl(`/api/v1/demo/electronics-shop?${params}`));
      if (!response.ok) throw new Error(`Assessment unavailable (${response.status})`);
      const data = await response.json();
      setHistory(data.history || null);
      setSkus(data.skus); setSku(data.assessment.sku); setTime(data.scenario_time); setResult(data.assessment);
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  return <main className={styles.page}><div className={styles.shell}>
    <h1>Electronics shop simulation</h1>
    <p>Catalogue snapshots with fictional stock and supplier offers. Read-only scenario replay; no messages or purchases.</p>
    <form onSubmit={event => { event.preventDefault(); void assess(); }}>
      <label>Requested units <input type="number" min="1" max="1000" required value={quantity}
        disabled={busy} onChange={event => { setQuantity(event.target.value); setResult(null); }} /></label>
      {skus.length > 0 && <label>Scenario product <select value={sku} disabled={busy}
        onChange={event => { setSku(event.target.value); setResult(null); }}>
        {skus.map(item => <option key={item}>{item}</option>)}
      </select></label>}
      <button disabled={busy} type="submit">{busy ? 'Assessing…' : 'Assess request'}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {result && <section className={styles.card}>
      <p>Fixed scenario time: {time}</p>
      <p>Unreserved units: {result.available} · Shortfall: <strong data-testid="shortfall">{result.shortfall}</strong></p>
      <p>Total retail price: {result.retail_total_cents === null ? 'Unknown' : `AUD ${(result.retail_total_cents / 100).toFixed(2)}`}</p>
      {result.supplier_offers.map(offer => <div key={offer.supplier_id}>
        <p>Fictional supplier offer: {offer.order_quantity} units at AUD {(offer.unit_cost_cents / 100).toFixed(2)} each;
          order total AUD {(offer.order_cost_cents / 100).toFixed(2)}.</p>
        <p>{offer.available_now} units available in the scenario; {offer.later_quantity} later ({offer.later_arrival}).</p>
        <p>Still uncovered after this offer: {offer.uncovered_shortfall} units.</p>
      </div>)}
      <p>Delivery unconfirmed · Commerce authority none</p>
      {history && <details data-testid="operational-history"><summary>Operational history</summary>
        <p>Fictional movements reconstructed from the scenario fixture; these are not executed orders.</p>
        {history.locations.map(row => <p key={row.location_id}>{row.location_id}: {row.on_hand} on hand, {row.reserved} reserved, {row.available} available</p>)}
        <ol>{history.events.map(event => <li key={event.sequence}>{event.location_id} — {event.kind}: {event.quantity} units</li>)}</ol>
      </details>}
      <details><summary>Request audit reference</summary><code data-testid="request-digest">{result.request_digest}</code></details>
    </section>}
  </div></main>;
}
