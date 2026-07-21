import { useRef, useEffect, useState } from 'react';
import styles from './ChatOverlay.module.css';
import type { Product } from '../App';
import { focusFirst, trapFocus } from '../utils/a11y';
import { formatProductPrice } from '../lib/money';

// Honest price: from price OR price_cents; em-dash (not "$0") when the object carries no price.
function priceText(p: any): string {
  return formatProductPrice(p);
}

// Inline SVG icons to avoid heroicons dependency issues
const CogIcon = () => (
  <svg className={styles.traceIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 15a3 3 0 100-6 3 3 0 000 6z" />
    <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z" />
  </svg>
);

export default function ChatOverlay({
  open,
  onClose,
  onSend,
  products,
  traceId,
  onOpenTrace,
}: {
  open: boolean;
  onClose: () => void;
  onSend: (query: string) => void;
  products: Product[];
  traceId: string | null;
  onOpenTrace: () => void;
}) {
  const [q, setQ] = useState('');
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const titleId = 'chat-overlay-title';

  // Focus management: move focus into dialog when opened, restore when closed
  const previousFocusRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement;
      focusFirst(dialogRef.current);
      const cleanup = trapFocus(dialogRef.current!);
      return cleanup;
    } else {
      previousFocusRef.current?.focus();
    }
  }, [open]);

  const handleSend = () => {
    if (q.trim()) {
      onSend(q);
      setQ('');
    }
  };

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-hidden={!open}
      className={`${styles.wrap} ${open ? styles.open : ''}`}
    >
      <div className={styles.header}>
        <span id={titleId} className={styles.headerTitle}>ShopSquire AI Assistant</span>
        <button
          className={styles.closeBtn}
          onClick={onClose}
          aria-label="Close chat assistant"
        >Close</button>
      </div>

      <div className={styles.body}>
        {/* Quick Action Buttons */}
        <div className={styles.quickActions} role="group" aria-label="Quick search suggestions">
          <button className={styles.quickBtn} onClick={() => onSend('budget laptop under $1000')}>Budget</button>
          <button className={styles.quickBtn} onClick={() => onSend('gaming laptop RTX')}>Gaming</button>
          <button className={styles.quickBtn} onClick={() => onSend('compare top laptops')}>Compare</button>
          <button className={styles.quickBtn} onClick={() => onSend('16GB RAM laptop')}>16GB RAM</button>
          <button className={styles.quickBtn} onClick={() => onSend('laptop details specs')}>Detailed View</button>
        </div>

        {/* Product Results */}
        {products.length > 0 ? (
          <>
            {products.slice(0, 5).map((p) => (
              <div key={p.sku} className={styles.card} role="article" aria-label={`Product: ${p.name}`}>
                <div className={styles.cardImage}>
                  <img
                    src={p.image_url || `/static/images/${p.sku}.svg`}
                    alt={`Product image for ${p.name}`}
                    onError={(e) => { (e.target as HTMLImageElement).src = '/static/images/placeholder.svg'; }}
                  />
                </div>
                <div className={styles.cardContent}>
                  <div className={styles.cardName}>{p.name}</div>
                  <div className={styles.cardPrice} aria-label={`Price: ${priceText(p)}`}>{priceText(p)}</div>
                  <div className={styles.cardFeatures}>{(p.features || []).slice(1, 3).join(' • ')}</div>
                </div>
                <button className={styles.addBtn} aria-label={`Add ${p.name} to cart`}>Add</button>
              </div>
            ))}
            {products.length > 5 && (
              <div style={{ textAlign: 'center', color: '#6b7280', fontSize: 13, marginTop: 8 }}>
                + {products.length - 5} more products
              </div>
            )}
            {traceId && (
              <button className={styles.traceBtn} onClick={onOpenTrace}>
                <CogIcon />
                <span>Why this recommendation?</span>
              </button>
            )}
          </>
        ) : (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>💬</div>
            <div className={styles.emptyText}>Ask me anything about laptops!</div>
            <div className={styles.emptyHint}>Try "gaming laptop under $2000" or "compare MacBooks"</div>
          </div>
        )}
      </div>

      <div className={styles.footer}>
        <label htmlFor="chat-input" className="sr-only">Ask ShopSquire anything</label>
        <input
          id="chat-input"
          ref={inputRef}
          className={styles.input}
          placeholder="Ask about laptops..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          aria-label="Chat message input"
        />
        <button
          className={styles.sendBtn}
          onClick={handleSend}
          aria-label="Send message"
          disabled={!q.trim()}
        >Send</button>
      </div>
    </div>
  );
}
