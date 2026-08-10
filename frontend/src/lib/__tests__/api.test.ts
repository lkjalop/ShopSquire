import { describe, expect, it } from 'vitest';

import { resolveImplicitApiBase } from '../api';

describe('resolveImplicitApiBase', () => {
  it('uses the same-origin Vite proxy in a clean local checkout', () => {
    expect(resolveImplicitApiBase({
      protocol: 'http:',
      hostname: 'localhost',
      host: 'localhost:5173',
      port: '5173',
    })).toBe('');
  });

  it('keeps a directly hosted API origin explicit', () => {
    expect(resolveImplicitApiBase({
      protocol: 'http:',
      hostname: '127.0.0.1',
      host: '127.0.0.1:8080',
      port: '8080',
    })).toBe('http://127.0.0.1:8080');
  });
});
