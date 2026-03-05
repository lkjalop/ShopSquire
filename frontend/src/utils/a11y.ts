/**
 * frontend/src/utils/a11y.ts — Accessibility utilities for ShopSquire.
 *
 * Guidelines applied throughout the UI:
 *   1. All interactive elements have accessible labels (aria-label / aria-labelledby).
 *   2. Live regions announce async updates to screen readers.
 *   3. Focus management for dialogs/modals.
 *   4. Keyboard navigation (Enter/Space for custom button roles).
 *   5. Colour contrast is enforced in CSS (not enforced here, tracked separately).
 */

/**
 * Returns keyboard handler props that trigger a click on Enter or Space,
 * turning non-button elements into keyboard-accessible controls.
 * Only use for elements with role="button" — prefer <button> whenever possible.
 */
export function keyboardClickProps(onClick: (e?: React.KeyboardEvent) => void) {
  return {
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onClick(e);
      }
    },
  };
}

/**
 * Move focus to the first focusable descendant of a container.
 * Call this when opening a modal or dialog.
 */
export function focusFirst(container: HTMLElement | null): void {
  if (!container) return;
  const focusable = container.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  );
  if (focusable.length > 0) {
    focusable[0].focus();
  }
}

/**
 * Trap focus within a container element (e.g., a modal).
 * Returns a cleanup function that removes the event listener.
 */
export function trapFocus(container: HTMLElement): () => void {
  const focusableSelector =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  const handler = (e: KeyboardEvent) => {
    if (e.key !== 'Tab') return;
    const nodes = Array.from(container.querySelectorAll<HTMLElement>(focusableSelector));
    if (!nodes.length) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  container.addEventListener('keydown', handler);
  return () => container.removeEventListener('keydown', handler);
}

/**
 * Generate a stable unique id for aria-labelledby / aria-describedby connections.
 * E.g.  const { id, labelId } = useA11yIds('cart-dialog');
 */
let _idCounter = 0;
export function generateA11yId(prefix: string): string {
  return `${prefix}-${++_idCounter}`;
}

/**
 * Announce a message to screen readers via an aria-live region.
 * Creates a transient off-screen element if the live region doesn't exist yet.
 */
export function announce(message: string, politeness: 'polite' | 'assertive' = 'polite'): void {
  const id = `shopsquire-live-${politeness}`;
  let region = document.getElementById(id);
  if (!region) {
    region = document.createElement('div');
    region.id = id;
    region.setAttribute('aria-live', politeness);
    region.setAttribute('aria-atomic', 'true');
    region.setAttribute('role', politeness === 'assertive' ? 'alert' : 'status');
    // Visually hidden but accessible to screen readers
    Object.assign(region.style, {
      position: 'absolute',
      width: '1px',
      height: '1px',
      padding: '0',
      margin: '-1px',
      overflow: 'hidden',
      clip: 'rect(0, 0, 0, 0)',
      whiteSpace: 'nowrap',
      border: '0',
    });
    document.body.appendChild(region);
  }
  // Clear and re-set to ensure announcement fires even for repeat messages
  region.textContent = '';
  requestAnimationFrame(() => {
    if (region) region.textContent = message;
  });
}
