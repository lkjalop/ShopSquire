import { useEffect, useState } from 'react';

export default function SecurityDemo({ onClose }: { onClose: () => void }) {
  const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';
  const DEV_API_KEY = ((import.meta as any).env?.VITE_DEVELOPER_API_KEY as string | undefined) || API_KEY;
  const [events, setEvents] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    const to = setTimeout(() => ctl.abort(), 10000);
    fetch('/api/v1/security/demo/events', {
      credentials: 'include',
      headers: DEV_API_KEY ? { 'x-api-key': DEV_API_KEY } : undefined,
      signal: ctl.signal,
    })
      .then((r) => {
        clearTimeout(to);
        if (!r.ok) throw new Error('forbidden');
        return r.json();
      })
      .then((d) => setEvents(d.events || []))
      .catch((e) => setError(e.message));
  }, [DEV_API_KEY]);
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.4)', display: 'grid', placeItems: 'center', zIndex: 50 }}>
      <div style={{ background: '#fff', borderRadius: 12, padding: 16, width: 560, maxWidth: '90vw', boxShadow: '0 10px 40px rgba(0,0,0,.2)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <strong>Security Demo (admin-only)</strong>
          <button onClick={onClose} style={{ padding: '6px 10px' }}>Close</button>
        </div>
        {error && <div style={{ marginTop: 10, color: '#9f2d1b' }}>Access denied: {error}</div>}
        {!error && (
          <div style={{ marginTop: 10 }}>
            {!events.length && <div>No recent events.</div>}
            {!!events.length && (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', borderBottom: '1px solid #eee', padding: 6 }}>Time</th>
                    <th style={{ textAlign: 'left', borderBottom: '1px solid #eee', padding: 6 }}>Severity</th>
                    <th style={{ textAlign: 'left', borderBottom: '1px solid #eee', padding: 6 }}>Technique</th>
                    <th style={{ textAlign: 'left', borderBottom: '1px solid #eee', padding: 6 }}>Action</th>
                    <th style={{ textAlign: 'left', borderBottom: '1px solid #eee', padding: 6 }}>User</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id}>
                      <td style={{ borderBottom: '1px solid #eee', padding: 6 }}>{e.time}</td>
                      <td style={{ borderBottom: '1px solid #eee', padding: 6 }}>{e.severity}</td>
                      <td style={{ borderBottom: '1px solid #eee', padding: 6 }}>{e.technique}</td>
                      <td style={{ borderBottom: '1px solid #eee', padding: 6 }}>{e.action}</td>
                      <td style={{ borderBottom: '1px solid #eee', padding: 6 }}>{e.user}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
