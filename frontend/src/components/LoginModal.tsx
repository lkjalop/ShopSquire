import { useState } from 'react';
import { apiUrl, safeJson } from '../lib/api';

interface Props {
  onClose: () => void;
  onLogin: (user: { user_id: string; email: string; name: string; role: string }) => void;
}

export default function LoginModal({ onClose, onLogin }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    setError(null);
    if (!email || !password) { setError('Email and password required'); return; }
    if (mode === 'register' && !name) { setError('Name required'); return; }
    setLoading(true);
    try {
      const endpoint = mode === 'login' ? '/api/v1/auth/login' : '/api/v1/auth/register';
      const body: Record<string, string> = { email, password };
      if (mode === 'register') body.name = name;
      const r = await fetch(apiUrl(endpoint), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const j = await safeJson(r);
      if (!r.ok) {
        setError(j?.detail || `Error ${r.status}`);
        return;
      }
      if (j?.access_token) localStorage.setItem('access_token', j.access_token);
      if (j?.refresh_token) localStorage.setItem('refresh_token', j.refresh_token);
      const role = j?.role || 'buyer';
      localStorage.setItem('role', role);
      if (j?.user_id) localStorage.setItem('uid', String(j.user_id));
      onLogin({ user_id: j?.user_id, email: j?.email || email, name: j?.name || name, role });
    } catch (e: any) {
      setError(e?.message || 'Network error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={overlay} onClick={onClose}>
      <div style={modal} onClick={e => e.stopPropagation()}>
        <h3 style={{ margin: '0 0 12px' }}>{mode === 'login' ? 'Login' : 'Register'}</h3>
        {mode === 'register' && (
          <input style={input} placeholder="Name" value={name} onChange={e => setName(e.target.value)} />
        )}
        <input style={input} placeholder="Email" type="email" value={email} onChange={e => setEmail(e.target.value)} />
        <input style={input} placeholder="Password" type="password" value={password} onChange={e => setPassword(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && submit()} />
        {error && <div style={{ color: '#e74c3c', fontSize: 13, marginBottom: 8 }}>{error}</div>}
        <button style={btn} onClick={submit} disabled={loading}>{loading ? '...' : mode === 'login' ? 'Login' : 'Register'}</button>
        <div style={{ fontSize: 13, marginTop: 8, textAlign: 'center' }}>
          {mode === 'login' ? (
            <span>No account? <button style={link} onClick={() => setMode('register')}>Register</button></span>
          ) : (
            <span>Have an account? <button style={link} onClick={() => setMode('login')}>Login</button></span>
          )}
        </div>
      </div>
    </div>
  );
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 9999,
};
const modal: React.CSSProperties = {
  background: '#fff', borderRadius: 10, padding: '28px 24px', minWidth: 320, maxWidth: 400,
  boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
};
const input: React.CSSProperties = {
  display: 'block', width: '100%', padding: '8px 10px', marginBottom: 10,
  border: '1px solid #ccc', borderRadius: 6, fontSize: 14, boxSizing: 'border-box',
};
const btn: React.CSSProperties = {
  width: '100%', padding: '10px 0', background: '#2563eb', color: '#fff', border: 'none',
  borderRadius: 6, fontSize: 15, cursor: 'pointer', fontWeight: 600,
};
const link: React.CSSProperties = {
  background: 'none', border: 'none', color: '#2563eb', cursor: 'pointer',
  textDecoration: 'underline', fontSize: 13, padding: 0,
};
