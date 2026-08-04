import styles from './ExternalResearchPanel.module.css';

// Safe-internet-search results are a SEPARATE, labeled source — never owned catalog items.
// An item is only "sold here" when the backend SKU-gate mapped it to a real catalog SKU; otherwise
// it is clearly marked "not sold by this store" and is structurally un-cartable (no Add-to-Cart).
export type ExternalResearchItem = {
  title: string;
  snippet?: string;
  source_domain?: string;
  url?: string;
  sku?: string | null;
  sold_here?: boolean;
  label?: string | null;
};

export default function ExternalResearchPanel({ items }: { items?: ExternalResearchItem[] }) {
  if (!items || items.length === 0) return null;
  return (
    <section className={styles.panel} data-testid="external-research">
      <div className={styles.header}>
        <span>From around the web</span>
        <span className={styles.disclaimer}>Informational results — not sold by this store unless tagged “Available here”.</span>
      </div>
      {items.map((it, i) => (
        <article key={`${it.url || it.title}-${i}`} className={styles.item}>
          <div className={styles.itemTitle}>{it.title}</div>
          {it.source_domain && <div className={styles.domain}>{it.source_domain}</div>}
          {it.snippet && <div className={styles.snippet}>{it.snippet}</div>}
          <div className={styles.footer}>
            {it.sold_here && it.sku ? (
              <span className={styles.soldHere} data-testid="sold-here">Available here</span>
            ) : (
              <span className={styles.notSold} data-testid="not-sold">{it.label || 'Not sold by this store'}</span>
            )}
            {it.url && (
              // rel guards against tabnabbing + tells crawlers this is untrusted external content.
              <a href={it.url} target="_blank" rel="noopener noreferrer nofollow" className={styles.link}>
                Source ↗
              </a>
            )}
          </div>
        </article>
      ))}
    </section>
  );
}
