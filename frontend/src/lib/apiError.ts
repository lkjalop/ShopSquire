export function apiErrorMessage(payload: any, fallback: string): string {
  const detail = payload?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string' && detail.message.trim()) return detail.message;
    if (typeof detail.code === 'string' && detail.code.trim()) return detail.code.replaceAll('_', ' ');
    if (Array.isArray(detail)) {
      const messages = detail.map((row) => row?.msg || row?.message).filter(Boolean);
      if (messages.length) return messages.join('; ');
    }
    try { return JSON.stringify(detail); } catch { return fallback; }
  }
  return fallback;
}
