import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import RecommendationShelf, { type RecommendationShelfContract } from '../RecommendationShelf';

const shelf: RecommendationShelfContract = {
  bands: [
    { id: 'closest_fit', label: 'Closest within budget - requirements not met', cards: [
      { sku: 'BASIC', name: 'Basic laptop', price: 999, currency: 'AUD' },
    ] },
    { id: 'stretch', label: 'Meets your needs - stretch from $1,799', cards: [
      { sku: 'GPU', name: 'GPU laptop', price: 1799, currency: 'AUD' },
    ] },
  ],
};

describe('RecommendationShelf', () => {
  it('keeps noncompliant and stretch products in explicitly labeled bands', () => {
    render(<RecommendationShelf shelf={shelf} onAdd={() => undefined} />);
    expect(screen.getByTestId('shelf-band-closest_fit')).toHaveTextContent('Requirements not fully met');
    expect(screen.getByTestId('shelf-band-stretch')).toHaveTextContent('Outside your stated budget');
    expect(screen.getByText('Basic laptop')).toBeTruthy();
    expect(screen.getByText('GPU laptop')).toBeTruthy();
  });

  it('preserves product actions', () => {
    const onAdd = vi.fn();
    const onWhy = vi.fn();
    render(<RecommendationShelf shelf={shelf} onAdd={onAdd} onWhy={onWhy} />);
    fireEvent.click(screen.getAllByRole('button', { name: 'Add' })[1]);
    fireEvent.click(screen.getAllByRole('button', { name: 'Why?' })[0]);
    expect(onAdd).toHaveBeenCalledWith('GPU');
    expect(onWhy).toHaveBeenCalledWith('BASIC');
  });

  it('keeps explanations visible while withholding cart actions without authority', () => {
    const onWhy = vi.fn();
    render(<RecommendationShelf shelf={shelf} onWhy={onWhy} />);
    expect(screen.queryByRole('button', { name: 'Add' })).toBeNull();
    fireEvent.click(screen.getAllByRole('button', { name: 'Why?' })[0]);
    expect(onWhy).toHaveBeenCalledWith('BASIC');
  });
});
