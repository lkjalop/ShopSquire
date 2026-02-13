import React, { useEffect, useState } from 'react';
import { cancelOrder, fetchOrders, returnOrder, updateOrderStatus } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

const statusLabels: Record<string, string> = {
  created: 'Created',
  paid: 'Paid',
  shipped: 'Shipped',
  delivered: 'Delivered',
  cancelled: 'Cancelled',
  return_requested: 'Return requested',
  returned: 'Returned',
};

const nextStatusMap: Record<string, { status: string; label: string } | null> = {
  created: { status: 'paid', label: 'Mark Paid' },
  paid: { status: 'shipped', label: 'Mark Shipped' },
  shipped: { status: 'delivered', label: 'Mark Delivered' },
  delivered: null,
  cancelled: null,
  return_requested: { status: 'returned', label: 'Mark Returned' },
  returned: null,
};

export function Orders({ role }: Props) {
  const [orders, setOrders] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    setLoading(true);
    setError('');
    fetchOrders()
      .then((d) => setOrders(d.orders || []))
      .catch(() => setError('Failed to load orders.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="stagger">
      <div className="panel">
        <strong>Order Lifecycle</strong>
        <div className="page-sub">MVP production flow: created → paid → shipped → delivered → return_requested/returned</div>
        <div style={{ marginTop: 8 }}>
          <button className="btn secondary" onClick={load}>Refresh</button>
        </div>
        {loading && <div className="page-sub" style={{ marginTop: 8 }}>Loading orders...</div>}
        {error && <div className="page-sub" style={{ marginTop: 8, color: '#9f2d1b' }}>{error}</div>}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Orders</h3>
        <table className="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Status</th>
              <th>Total</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => {
              const next = nextStatusMap[o.status] || null;
              const canCancel = ['created', 'paid'].includes(o.status);
              const canReturn = ['delivered'].includes(o.status);
              return (
              <tr key={o.order_id}>
                <td>{o.order_id}</td>
                <td>{statusLabels[o.status] || o.status}</td>
                <td>${Math.round((o.total_cents || 0) / 100)}</td>
                <td>{o.created_at}</td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {next && (
                      <button
                        className="btn"
                        onClick={async () => {
                          await updateOrderStatus(o.order_id, next.status);
                          load();
                        }}
                      >
                        {next.label}
                      </button>
                    )}
                    <button
                      className="btn secondary"
                      disabled={!canCancel}
                      onClick={async () => {
                        await cancelOrder(o.order_id);
                        load();
                      }}
                    >
                      Cancel
                    </button>
                    <button
                      className="btn secondary"
                      disabled={!canReturn}
                      onClick={async () => {
                        await returnOrder(o.order_id);
                        load();
                      }}
                    >
                      Return
                    </button>
                  </div>
                </td>
              </tr>
              );
            })}
            {orders.length === 0 && !loading && (
              <tr>
                <td colSpan={5}>No orders yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
