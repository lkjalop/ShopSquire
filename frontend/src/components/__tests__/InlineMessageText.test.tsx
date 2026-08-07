import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import InlineMessageText from '../InlineMessageText';

describe('InlineMessageText', () => {
  it('renders bounded double-asterisk emphasis without exposing markup', () => {
    render(<InlineMessageText text="Nice choice! **Lenovo Legion Pro 7** was added." />);

    expect(screen.getByText('Lenovo Legion Pro 7').tagName).toBe('STRONG');
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument();
  });

  it('leaves unmatched markers as ordinary text', () => {
    render(<InlineMessageText text="A literal ** marker" />);
    expect(screen.getByText('A literal ** marker')).toBeInTheDocument();
  });
});
