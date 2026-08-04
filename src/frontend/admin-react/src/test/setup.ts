// vitest setup — registers @testing-library/jest-dom matchers (toBeInTheDocument, etc.)
// and tears down the rendered tree between tests so component tests stay isolated.
import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
});
