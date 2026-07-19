const AUTH_EMAIL_KEY = 'auth_email';
const AUTH_NAME_KEY = 'auth_name';
const ROLE_KEY = 'role';
const UID_KEY = 'uid';
const OWNER_KEY = 'ss_owner_key';

function session(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

export function getStoredAuthIdentity(): { email: string; name: string } | null {
  const s = session();
  if (!s) return null;
  const email = String(s.getItem(AUTH_EMAIL_KEY) || '').trim();
  const name = String(s.getItem(AUTH_NAME_KEY) || '').trim();
  return email ? { email, name: name || email } : null;
}

export function setStoredAuthIdentity(email: string, name: string): void {
  const s = session();
  if (!s) return;
  s.setItem(AUTH_EMAIL_KEY, String(email || ''));
  s.setItem(AUTH_NAME_KEY, String(name || email || ''));
}

export function clearStoredAuthIdentity(): void {
  const s = session();
  if (!s) return;
  s.removeItem(AUTH_EMAIL_KEY);
  s.removeItem(AUTH_NAME_KEY);
}

export function getStoredRole(): string {
  const s = session();
  return s ? String(s.getItem(ROLE_KEY) || '') : '';
}

export function setStoredRole(role: string): void {
  const s = session();
  if (!s) return;
  s.setItem(ROLE_KEY, String(role || ''));
}

export function clearStoredRole(): void {
  const s = session();
  if (!s) return;
  s.removeItem(ROLE_KEY);
}

export function getStoredUid(): string {
  const s = session();
  return s ? String(s.getItem(UID_KEY) || '') : '';
}

export function getOrCreateStoredUid(): string {
  const existing = getStoredUid().trim();
  if (existing) return existing;
  let suffix = '';
  try {
    suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2, 18);
  } catch {
    suffix = Math.random().toString(36).slice(2, 18);
  }
  const uid = `guest-${suffix}`.slice(0, 128);
  setStoredUid(uid);
  return uid;
}

export function setStoredUid(uid: string): void {
  const s = session();
  if (!s) return;
  s.setItem(UID_KEY, String(uid || ''));
}

export function clearStoredUid(): void {
  const s = session();
  if (!s) return;
  s.removeItem(UID_KEY);
}

export function getOwnerApiKey(): string {
  const s = session();
  const stored = s ? String(s.getItem(OWNER_KEY) || '').trim() : '';
  if (stored) return stored;
  // Fall back to build-time env var (VITE_OWNER_API_KEY in .env.local)
  const envKey = String((import.meta as any).env?.VITE_OWNER_API_KEY || '').trim();
  return envKey;
}

export function setOwnerApiKey(value: string): void {
  const s = session();
  if (!s) return;
  s.setItem(OWNER_KEY, String(value || '').trim());
}

export function clearOwnerApiKey(): void {
  const s = session();
  if (!s) return;
  s.removeItem(OWNER_KEY);
}

export function incidentTokenCookieName(incidentId: string): string {
  const safe = String(incidentId || '').replace(/[^a-zA-Z0-9]/g, '').slice(0, 48) || 'default';
  return `ss_incident_token_${safe}`;
}

export function setIncidentTokenCookie(incidentId: string, token: string): void {
  if (typeof document === 'undefined') return;
  const name = incidentTokenCookieName(incidentId);
  document.cookie = `${name}=${encodeURIComponent(token)}; Path=/; SameSite=Strict`;
}

export function clearIncidentTokenCookie(incidentId: string): void {
  if (typeof document === 'undefined') return;
  const name = incidentTokenCookieName(incidentId);
  document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Strict`;
}
