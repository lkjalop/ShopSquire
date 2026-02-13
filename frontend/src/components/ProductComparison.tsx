import styles from './ProductComparison.module.css';
import { CogIcon } from '@heroicons/react/24/outline';
import type { Product } from '../App';

type Matrix = Record<string, Record<string, string | null>>;

export default function ProductComparison({ products, order, matrix, onAdd, onTrace }: { products: Product[]; order?: string[]; matrix?: Matrix; onAdd: (sku: string) => void; onTrace: () => void }) {
  const cols = (order && order.length ? order.map((sku) => products.find((p) => p.sku === sku)).filter(Boolean) as Product[] : products.slice(0, 3));
  const keys = ['processor', 'RAM', 'battery', 'display', 'graphics'];
  return (
    <div style={{ padding: 12 }}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th></th>
            {cols.map((p) => (
              <th key={p.sku} className={styles.head}>
                {p.name}<div>${p.price}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <td className={styles.head}>{k[0].toUpperCase() + k.slice(1)}</td>
              {cols.map((p) => (
                <td key={p.sku + k}>
                  {matrix?.[p.sku]?.[k] ?? (p.features || []).find((f) => f.toLowerCase().includes(k.toLowerCase())) ?? '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className={styles.actions}>
        <button className={styles.btn} onClick={() => cols[0] && onAdd(cols[0].sku)}>Add {cols[0]?.name}</button>
        <button className={styles.btn} onClick={onTrace} aria-label="Why this recommendation">
          <CogIcon className="icon" aria-hidden="true" /> <span style={{ marginLeft: 8 }}>Why this recommendation?</span>
        </button>
      </div>
    </div>
  );
}
