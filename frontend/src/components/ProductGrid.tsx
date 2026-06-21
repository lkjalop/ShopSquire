import styles from './ProductGrid.module.css';
import type { Product } from '../App';
import { productDisplayName, productSubtitle } from '../lib/productDisplay';

const LAPTOP_PLACEHOLDER = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 150" fill="none"><rect width="200" height="150" fill="#f3f4f6"/><rect x="30" y="20" width="140" height="85" rx="4" fill="#e5e7eb" stroke="#d1d5db" stroke-width="2"/><rect x="35" y="25" width="130" height="75" rx="2" fill="#fff"/><rect x="50" y="105" width="100" height="8" rx="2" fill="#d1d5db"/><rect x="45" y="113" width="110" height="3" rx="1" fill="#e5e7eb"/><circle cx="100" cy="62" r="20" fill="#e5e7eb"/><path d="M92 62l6 6 12-12" stroke="#9ca3af" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>')}`;

// Stock honesty — surface the backend's per-item stock_status so a shopper never discovers an item
// is out of stock only at checkout. Unknown/missing status renders no badge (no false signal).
const STOCK_META: Record<string, { label: string; cls: string }> = {
  in_stock: { label: 'In stock', cls: styles.inStock },
  low_stock: { label: 'Low stock', cls: styles.lowStock },
  very_low_stock: { label: 'Very low stock', cls: styles.veryLowStock },
  out_of_stock: { label: 'Out of stock', cls: styles.outOfStock },
};

export function isOutOfStock(p: Product): boolean {
  // cart_eligible is the backend's authoritative gate; stock_status is the fallback signal.
  return p.cart_eligible === false || p.stock_status === 'out_of_stock';
}

function StockBadge({ p }: { p: Product }) {
  const meta = p.stock_status ? STOCK_META[p.stock_status] : undefined;
  if (!meta) return null;
  const urgency = p.stock_urgency && p.stock_status !== 'out_of_stock' ? ` — ${p.stock_urgency}` : '';
  return (
    <div className={`${styles.stockBadge} ${meta.cls}`} data-testid="stock-badge">
      {meta.label}{urgency}
    </div>
  );
}

function AddToCartButton({ p, onAdd }: { p: Product; onAdd?: (sku: string) => void }) {
  const oos = isOutOfStock(p);
  return (
    <button
      className={styles.addBtn}
      disabled={oos}
      aria-disabled={oos}
      onClick={() => { if (!oos && onAdd) onAdd(p.sku); }}
    >
      {oos ? 'Out of stock' : 'Add to Cart'}
    </button>
  );
}

export default function ProductGrid({ products, onToggle, onAdd, onWhy, viewMode = 'grid' }: {
  products: Product[];
  onToggle?: (sku: string, checked: boolean) => void;
  onAdd?: (sku: string) => void;
  onWhy?: (sku: string) => void;
  viewMode?: 'grid' | 'list' | 'detailed';
}) {
  if (viewMode === 'detailed') {
    return (
      <section className={styles.detailedList}>
        {products.map((p) => {
          const title = productDisplayName(p);
          const subtitle = productSubtitle(p);
          return (
            <article key={p.sku} className={styles.detailedCard}>
              <div className={styles.detailedImage}>
                <img
                  src={p.image_url || LAPTOP_PLACEHOLDER}
                  alt={title}
                  onError={(e) => { (e.target as HTMLImageElement).src = LAPTOP_PLACEHOLDER; }}
                />
              </div>
              <div className={styles.detailedInfo}>
                <h3 className={styles.detailedTitle}>{title}</h3>
                {subtitle && <div className={styles.features} style={{ marginTop: 4 }}>{subtitle}</div>}
                <div className={styles.detailedPrice}>${p.price.toLocaleString()}</div>
                <StockBadge p={p} />
                {(p.why && p.why.length > 0) && (
                  <div className={styles.features} style={{ marginTop: 6 }}>
                    {p.why.slice(0, 3).join(' • ')}
                  </div>
                )}
                <ul className={styles.featuresList}>
                  {(p.features || []).slice(1).map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
                <div className={styles.detailedActions}>
                  <AddToCartButton p={p} onAdd={onAdd} />
                  <button className={styles.detailsBtn}>View Details</button>
                  {onWhy && <button className={styles.detailsBtn} onClick={() => onWhy(p.sku)}>Why this product</button>}
                </div>
              </div>
            </article>
          );
        })}
      </section>
    );
  }

  return (
    <section className={styles.grid}>
      {products.map((p) => {
        const title = productDisplayName(p);
        const subtitle = productSubtitle(p);
        return (
          <article key={p.sku} className={styles.card}>
            <div className={styles.imageWrap}>
              <img
                src={p.image_url || LAPTOP_PLACEHOLDER}
                alt={title}
                className={styles.productImage}
                onError={(e) => { (e.target as HTMLImageElement).src = LAPTOP_PLACEHOLDER; }}
              />
              {onToggle && (
                <input
                  type="checkbox"
                  className={styles.selectBox}
                  aria-label={`Select ${title}`}
                  onChange={(e) => onToggle(p.sku, e.currentTarget.checked)}
                />
              )}
            </div>
            <div className={styles.cardContent}>
              <div className={styles.title}>{title}</div>
              {subtitle && <div className={styles.features}>{subtitle}</div>}
              <div className={styles.price}>${p.price.toLocaleString()}</div>
              <StockBadge p={p} />
              {(p.why && p.why.length > 0) && (
                <div className={styles.features}>{p.why.slice(0, 3).join(' • ')}</div>
              )}
              <div className={styles.features}>{(p.features || []).slice(1, 3).join(' • ')}</div>
              <div className={styles.actions}>
                <AddToCartButton p={p} onAdd={onAdd} />
                {onWhy && <button className={styles.detailsBtn} onClick={() => onWhy(p.sku)}>Why this product</button>}
                <a href={`/ui/product/${p.sku}`} className={styles.detailsLink}>Details</a>
              </div>
            </div>
          </article>
        );
      })}
    </section>
  );
}
