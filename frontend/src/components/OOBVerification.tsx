/**
 * OOB Verification UI hook — embeddable component for the Escalation Console.
 *
 * Usage in EscalationRoom or SecurityDemo:
 *   import OOBVerification from './OOBVerification';
 *   <OOBVerification vendorDomain="supplier.com" triggerSignal="bank_fingerprint_baseline_mismatch" />
 */
import React, { useState, useCallback } from 'react';
import { apiFetch } from '../lib/csrf';

const API_BASE = '/api/v1/oob';

interface OOBProps {
  vendorDomain: string;
  triggerSignal: string;
  invoiceRef?: string;
  amount?: string;
  channel?: 'sms' | 'email' | 'phone_call';
  destination?: string;
  traceId?: string;
}

interface OOBState {
  requestId: string | null;
  token: string | null;
  status: string | null;
  error: string | null;
  loading: boolean;
}

export default function OOBVerification({
  vendorDomain,
  triggerSignal,
  invoiceRef = '',
  amount = '',
  channel = 'email',
  destination = '',
  traceId = '',
}: OOBProps) {
  const [state, setState] = useState<OOBState>({
    requestId: null,
    token: null,
    status: null,
    error: null,
    loading: false,
  });

  const [confirmToken, setConfirmToken] = useState('');

  const createOOB = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await apiFetch<any>(`${API_BASE}/create`, {
        method: 'POST',
        body: JSON.stringify({
          vendor_domain: vendorDomain,
          trigger_signal: triggerSignal,
          invoice_ref: invoiceRef,
          amount,
          channel,
          destination,
          trace_id: traceId,
        }),
      });
      setState({
        requestId: data.request_id,
        token: data.token,
        status: data.status,
        error: null,
        loading: false,
      });
    } catch (err: any) {
      setState((s) => ({ ...s, loading: false, error: err.message }));
    }
  }, [vendorDomain, triggerSignal, invoiceRef, amount, channel, destination, traceId]);

  const confirmOOB = useCallback(async () => {
    if (!state.requestId) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await apiFetch<any>(`${API_BASE}/confirm`, {
        method: 'POST',
        body: JSON.stringify({ request_id: state.requestId, token: confirmToken }),
      });
      setState((s) => ({
        ...s,
        status: data.status || (data.ok ? 'confirmed' : s.status),
        error: data.error || null,
        loading: false,
      }));
    } catch (err: any) {
      setState((s) => ({ ...s, loading: false, error: err.message }));
    }
  }, [state.requestId, confirmToken]);

  const denyOOB = useCallback(async () => {
    if (!state.requestId) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      await apiFetch(`${API_BASE}/deny?request_id=${encodeURIComponent(state.requestId)}`, {
        method: 'POST',
      });
      setState((s) => ({ ...s, status: 'denied', loading: false }));
    } catch (err: any) {
      setState((s) => ({ ...s, loading: false, error: err.message }));
    }
  }, [state.requestId]);

  return (
    <div style={{ border: '1px solid #e5a00d', padding: 12, borderRadius: 8, marginTop: 8, background: '#fffbe6' }}>
      <strong>OOB Bank-Change Verification</strong>
      <div style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>
        Vendor: {vendorDomain} &middot; Signal: {triggerSignal}
      </div>

      {!state.requestId && (
        <button onClick={createOOB} disabled={state.loading}>
          {state.loading ? 'Sending...' : 'Send OOB Verification'}
        </button>
      )}

      {state.requestId && state.status !== 'confirmed' && state.status !== 'denied' && (
        <div>
          <p>Request: <code>{state.requestId}</code> — Status: <strong>{state.status}</strong></p>
          <input
            placeholder="Enter OOB token"
            value={confirmToken}
            onChange={(e) => setConfirmToken(e.target.value)}
            style={{ marginRight: 8 }}
          />
          <button onClick={confirmOOB} disabled={state.loading || !confirmToken}>Confirm</button>
          <button onClick={denyOOB} disabled={state.loading} style={{ marginLeft: 8, color: 'red' }}>Deny</button>
        </div>
      )}

      {state.status === 'confirmed' && <p style={{ color: 'green' }}>Verified — payment change approved.</p>}
      {state.status === 'denied' && <p style={{ color: 'red' }}>Denied — payment change blocked.</p>}
      {state.error && <p style={{ color: 'red' }}>Error: {state.error}</p>}
    </div>
  );
}
