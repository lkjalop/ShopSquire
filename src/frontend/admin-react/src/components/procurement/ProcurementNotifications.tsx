// ProcurementNotifications — the operator "needs attention" banner. Polls the notification feed (new cart
// confirmations, amendments/supersessions, supplier out-of-band events) so the operator learns immediately
// instead of only on a manual queue refresh. "Mark all seen" clears the badge.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { fcNotifications, fcMarkNotificationsSeen, type ProcurementNotification } from '../../api';

export default function ProcurementNotifications({ onActivity, pollMs = 6000 }:
  { onActivity?: () => void; pollMs?: number }) {
  const [items, setItems] = useState<ProcurementNotification[]>([]);
  const [unseen, setUnseen] = useState(0);
  const [busy, setBusy] = useState(false);
  const previousUnseen = useRef<number | null>(null);

  const load = useCallback(() => {
    fcNotifications(true, 10)
      .then((d) => {
        const nextUnseen = d.unseen || 0;
        setItems(d.notifications || []);
        setUnseen(nextUnseen);
        // The queue loads independently on mount. Refresh it only when new unseen work arrives;
        // an unchanged backlog must not refetch the full case list on every polling interval.
        if (previousUnseen.current !== null && nextUnseen > previousUnseen.current) onActivity?.();
        previousUnseen.current = nextUnseen;
      })
      .catch(() => { /* feed is best-effort; never block the control room */ });
  }, [onActivity]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!pollMs) return;
    const t = setInterval(load, pollMs);
    return () => clearInterval(t);
  }, [pollMs, load]);

  const markAll = async () => {
    setBusy(true);
    try {
      await fcMarkNotificationsSeen();
      setItems([]);
      setUnseen(0);
      previousUnseen.current = 0;
    }
    catch { /* ignore */ }
    finally { setBusy(false); }
  };

  if (unseen <= 0) return null;

  return (
    <div data-testid="proc-notifications" role="status"
         style={{ marginBottom: 12, padding: '8px 12px', borderRadius: 8, border: '1px solid #fcd34d',
                  background: '#fffbeb', color: '#7c2d12' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <strong data-testid="proc-notif-badge">{unseen} new procurement update{unseen === 1 ? '' : 's'}</strong>
        <button className="btn" data-testid="proc-notif-seen" disabled={busy} onClick={markAll}
                style={{ marginLeft: 'auto' }}>
          {busy ? '…' : 'Mark all seen'}
        </button>
      </div>
      <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 13 }}>
        {items.slice(0, 5).map((n) => (
          <li key={n.id} data-testid="proc-notif-item">{n.summary}</li>
        ))}
      </ul>
    </div>
  );
}
