import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import AttachmentButton from '../AttachmentButton';


describe('AttachmentButton', () => {
  it('offers image, PDF and TXT evidence without changing the camera contract', () => {
    const { container } = render(<AttachmentButton onFiles={vi.fn()} />);

    expect(screen.getByRole('button', { name: /attach image or requirements document/i })).toBeVisible();
    const inputs = [...container.querySelectorAll<HTMLInputElement>('input[type="file"]')];
    expect(inputs).toHaveLength(2);
    expect(inputs[0].accept).toContain('image/*');
    expect(inputs[0].accept).not.toContain('.pdf');
    expect(inputs[1].accept).toContain('.pdf');
    expect(inputs[1].accept).toContain('.txt');
  });
});
