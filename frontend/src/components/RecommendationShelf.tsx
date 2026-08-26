import type { Product } from '../App';
import { formatProductPrice } from '../lib/money';
import styles from './RecommendationShelf.module.css';

export type RecommendationShelfBand = {
  id: string;
  label: string;
  basis?: string;
  cards: Product[];
};

export type RecommendationShelfContract = {
  banner?: {
    kind?: string;
    text?: string;
    floor_cents?: number | null;
    budget_max_cents?: number | null;
  };
  bands: RecommendationShelfBand[];
};

type Props = {
  shelf: RecommendationShelfContract;
  onAdd?: (sku: string) => void;
  onWhy?: (sku: string) => void;
};

function bandTone(id: string): string {
  if (id === 'closest_fit') return styles.warning;
  if (id === 'stretch') return styles.stretch;
  return styles.primary;
}

function bandExplanation(id: string): string | null {
  if (id === 'target_fit') return 'Closest qualified options to the price you named';
  if (id === 'value_fit') return 'Lower cost, while still meeting the accepted requirements';
  if (id === 'maximum_capability') return 'More of the budget buys verified capability headroom';
  return null;
}

export default function RecommendationShelf({ shelf, onAdd, onWhy }: Props) {
  const bands = (shelf.bands || []).filter((band) => Array.isArray(band.cards) && band.cards.length > 0);
  if (bands.length === 0) return null;

  return (
    <div className={styles.shelf} data-testid="recommendation-shelf">
      {bands.map((band) => (
        <section className={`${styles.band} ${bandTone(band.id)}`} key={band.id} data-testid={`shelf-band-${band.id}`}>
          <header className={styles.header}>
            <h3>{band.label}</h3>
            {band.id === 'closest_fit' && <span>Requirements not fully met</span>}
            {band.id === 'stretch' && <span>Outside your stated budget</span>}
            {bandExplanation(band.id) && <span>{bandExplanation(band.id)}</span>}
          </header>
          <div className={styles.cards}>
            {band.cards.map((product) => (
              <article className={styles.card} key={`${band.id}-${product.sku}`}>
                {product.image_url && <img src={product.image_url} alt="" className={styles.image} />}
                <div className={styles.name}>{product.name}</div>
                <div className={styles.price}>{formatProductPrice(product)}</div>
                <div className={styles.actions}>
                  {onAdd && (
                    <button type="button" className={styles.add} onClick={() => onAdd(product.sku)}>Add</button>
                  )}
                  {onWhy && <button type="button" className={styles.why} onClick={() => onWhy(product.sku)}>Why?</button>}
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
