import React from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AgentIntelligence } from './AgentIntelligence';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const claim = { id: 'claim-one', agent_name: 'stock-agent', claim_type: 'stock',
  claim_key: 'owned-stock-observation', claim_value: { units: 15 }, trust_score: 0.9, confidence: 0.8 };

function respond(claims: unknown, status = 200) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const trusted = String(url).includes('/trusted_claims');
    const body = trusted ? claims : { total_claims: 1, verified_claims: 1, accuracy_rate: 1, avg_trust_score: 0.9 };
    return new Response(JSON.stringify(body), { status: trusted ? status : 200 });
  }));
}

it('renders the backend trusted-claims envelope with structured claim values', async () => {
  respond({ agent_name: null, claim_type: null, count: 1, claims: [claim] });
  render(<AgentIntelligence role="owner" />);
  expect(await screen.findByText('owned-stock-observation')).toBeInTheDocument();
  expect(screen.getByText('stock-agent')).toBeInTheDocument();
  const row = screen.getByRole('row', { name: /stock-agent stock owned-stock-observation/ });
  expect(within(row).getByText('0.900')).toBeInTheDocument();
  expect(within(row).getByText('0.80')).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('accepts an empty successful envelope without reporting an outage', async () => {
  respond({ agent_name: null, claim_type: null, count: 0, claims: [] });
  render(<AgentIntelligence role="owner" />);
  await screen.findByText('Citation Memory - Layer 4');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.queryByText('High-Trust Agent Claims')).not.toBeInTheDocument();
});

it.each([
  ['null JSON', null],
  ['a legacy array', [claim]],
  ['a non-array claims field', { count: 1, claims: {} }],
  ['an invalid score', { count: 1, claims: [{ ...claim, trust_score: 'high' }] }],
])('shows a visible error for %s instead of leaving loading stuck', async (_name, value) => {
  respond(value);
  render(<AgentIntelligence role="owner" />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Trusted claims could not be loaded.');
  expect(screen.queryByText('Loading citation memory...')).not.toBeInTheDocument();
  expect(screen.queryByText('owned-stock-observation')).not.toBeInTheDocument();
});

it('shows a backend failure without disguising it as empty successful claims', async () => {
  respond({ detail: 'unavailable' }, 503);
  render(<AgentIntelligence role="owner" />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Trusted claims could not be loaded.');
  expect(screen.queryByText('Loading citation memory...')).not.toBeInTheDocument();
});
