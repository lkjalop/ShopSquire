/**
 * ExternalResearchPanel — safe-internet-search UX (Workstream item 4).
 * External results must be clearly labeled "not sold by this store" unless SKU-mapped, must link out
 * safely (rel=noopener), and must NEVER be cartable (no Add-to-Cart button anywhere).
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ExternalResearchPanel from '../ExternalResearchPanel';

describe('ExternalResearchPanel', () => {
  it('renders nothing when there are no items', () => {
    const { container } = render(<ExternalResearchPanel items={[]} />);
    expect(container.firstChild).toBeNull();
    expect(render(<ExternalResearchPanel />).container.firstChild).toBeNull();
  });

  it('labels an unmapped item "not sold by this store" and is not cartable', () => {
    render(<ExternalResearchPanel items={[
      { title: 'Some Laptop', source_domain: 'techradar.com', snippet: 'a review', sku: null, sold_here: false },
    ]} />);
    expect(screen.getByTestId('not-sold')).toHaveTextContent(/not sold by this store/i);
    // No cart affordance anywhere in the panel.
    expect(screen.queryByRole('button', { name: /add to cart/i })).toBeNull();
  });

  it('marks a SKU-mapped item "Available here"', () => {
    render(<ExternalResearchPanel items={[
      { title: 'Mapped Laptop', source_domain: 'shop.example.com', sku: 'GAM-1', sold_here: true },
    ]} />);
    expect(screen.getByTestId('sold-here')).toHaveTextContent(/available here/i);
  });

  it('uses the backend label when provided', () => {
    render(<ExternalResearchPanel items={[
      { title: 'X', sku: null, sold_here: false, label: 'not sold by this store' },
    ]} />);
    expect(screen.getByTestId('not-sold')).toHaveTextContent('not sold by this store');
  });

  it('external link opens safely (rel=noopener noreferrer nofollow)', () => {
    render(<ExternalResearchPanel items={[
      { title: 'X', url: 'https://techradar.com/x', sold_here: false },
    ]} />);
    const link = screen.getByRole('link', { name: /source/i }) as HTMLAnchorElement;
    expect(link.rel).toContain('noopener');
    expect(link.rel).toContain('noreferrer');
    expect(link.target).toBe('_blank');
  });
});
