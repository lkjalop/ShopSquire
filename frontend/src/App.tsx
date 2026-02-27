import { useEffect, useMemo, useState, useRef, useCallback } from 'react';
import styles from './App.module.css';
import ProductGrid from './components/ProductGrid';
import DecisionTrace from './components/DecisionTrace';
import EscalationRoom from './components/EscalationRoom';
import RightPanelExtras from './components/RightPanelExtras';
import { apiUrl, safeJson, getCart, addCartItem, removeCartItem, clearCart } from './lib/api';
import AttachmentButton from './components/AttachmentButton';
import DisambiguationButtons from './components/DisambiguationButtons';
import { useDualSTT } from './hooks/useDualSTT';
import CartPanel from './components/CartPanel';

export type Product = {
  sku: string;
  name: string;
  price: number;
  features?: string[];
  image_url?: string;
  why?: string[];
  score_norm?: number;
  why_codes?: { code: string; label: string; confidence: number; weight?: number; weighted_score?: number }[];
  why_confidence?: number;
  model_source?: string;
};
type RightPanelMode = 'none' | 'grid' | 'list' | 'compare' | 'cv' | 'cart' | 'faq' | 'security' | 'visual_search' | 'image_context';
type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  images?: string[];           // data-URL thumbnails shown inline
  disambiguation?: boolean;    // true → render DisambiguationButtons
  disambiguationOptions?: string[];
  nextQuestions?: { id: string; text: string; goal?: string }[];
  complexity?: { score: number; tier: string; model: string };
  voiceUsed?: boolean;
};
type PendingImageContext = {
  labels: string[];
  ocrText: string;
  imageHash?: string | null;
};

type BackendStatus = {
  ok: boolean;
  latencyMs: number | null;
  checkedAt: Date | null;
  error?: string | null;
};


function useProducts() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const ctl = new AbortController();
    fetch('/ui/products.json', { signal: ctl.signal })
      .then((r) => r.json())
      .then((d) => setProducts(Array.isArray(d) ? d : []))
      .catch(() => setProducts([]))
      .finally(() => setLoading(false));
    return () => ctl.abort();
  }, []);
  return { products, loading };
}

// PII Detection - Luhn algorithm for credit card validation
function luhnCheck(num: string): boolean {
  let sum = 0;
  let alt = false;
  for (let i = num.length - 1; i >= 0; i--) {
    let n = parseInt(num[i], 10);
    if (alt) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
    alt = !alt;
  }
  return sum % 10 === 0;
}

type PIIMatch = { type: string; advice: string } | null;

function detectPII(text: string): PIIMatch {
  // Credit card pattern (13-19 digits with optional spaces/dashes)
  const cardMatch = text.match(/\b(?:\d[ -]*?){13,19}\b/);
  if (cardMatch) {
    const digits = cardMatch[0].replace(/\D/g, '');
    if (digits.length >= 13 && digits.length <= 19) {
      // If it's a real-looking PAN (passes Luhn), block immediately.
      if (luhnCheck(digits)) {
        return {
          type: 'credit card number',
          advice: 'Never share payment card details in chat. Use our secure checkout instead.'
        };
      }

      // Demo/real-world: users often paste fake/test numbers that fail Luhn.
      // If strong card context is present (keywords or expiry), treat as PCI anyway.
      const hasCardHint = /\b(card|credit|debit|visa|mastercard|amex|american\s+express|discover)\b/i.test(text);
      const hasCvvHint = /\b(cvv|cvc|security\s*code|card\s*verification)\b/i.test(text);
      const hasExpiry = /\b(0[1-9]|1[0-2])\s*[/\-]\s*(\d{2}|\d{4})\b/.test(text);
      if (hasCardHint || hasCvvHint || hasExpiry) {
        return {
          type: 'payment card details',
          advice: 'Never share card numbers, expiry dates, or CVV in chat. Use secure checkout instead.'
        };
      }
    }
  }

  // SSN pattern
  if (/\b\d{3}-\d{2}-\d{4}\b/.test(text)) {
    return {
      type: 'Social Security Number',
      advice: 'SSNs should never be shared online. We will never ask for this information.'
    };
  }

  // Email in certain contexts (offering personal email)
  if (/\b(my email is|email me at|contact me at)\b/i.test(text) && /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/.test(text)) {
    return {
      type: 'email address',
      advice: 'For account inquiries, please use the Account section. We protect your privacy.'
    };
  }

  // Bank account numbers (8-17 digits preceded by keywords)
  if (/\b(account|routing|bank).{0,20}\d{8,17}\b/i.test(text)) {
    return {
      type: 'bank account information',
      advice: 'Never share banking details in chat. Contact our support team securely if needed.'
    };
  }

  return null;
}

function detectPanelMode(query: string): RightPanelMode {
  const q = query.toLowerCase();
  // Compare triggers
  if (/compare|vs|versus|difference|which is better|pros.?cons|side.?by.?side|head.?to.?head/.test(q)) return 'compare';
  // Detailed/specs triggers
  if (/specs|specification|details|detailed|features|info|information|describe|tell me about|breakdown/.test(q)) return 'list';
  // CV/return triggers (when images attached - handled separately)
  if (/return|complaint|damaged|broken|defective|refund|issue|problem/.test(q)) return 'cv';
  // FAQ triggers
  if (/faq|help|how do i|what is|shipping|warranty|policy|support/.test(q)) return 'faq';
  // Product search (default when products mentioned)
  if (/laptop|computer|price|under|below|above|budget|cheap|affordable|\$|show|find|search|gaming|macbook|dell|hp|asus|lenovo|msi/.test(q)) return 'grid';
  return 'none';
}

function isComplaintIntent(query: string): boolean {
  const q = query.toLowerCase();
  const action = /return|refund|complaint/.test(q);
  const damage = /damaged|broken|defective|issue|problem/.test(q);
  const evidence = /photo|picture|image|upload|evidence/.test(q);
  const policyOnly = /policy|eligibility|warranty|how do i|steps|process/.test(q);
  if (damage && (action || evidence)) return true;
  if (action && !policyOnly) return true;
  return false;
}

// SVG Icons
const ChatIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={styles.fabIcon}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>;
const CloseIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M18 6L6 18M6 6l12 12"/></svg>;
const GearIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>;
const DetachIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>;
const MicIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>;
const SendIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>;
const GridIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>;
const ListIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>;

export default function App() {
  const { products, loading } = useProducts();
  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [rightPanelMode, setRightPanelMode] = useState<RightPanelMode>('none');
  const [displayProducts, setDisplayProducts] = useState<Product[]>([]);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>({ ok: false, latencyMs: null, checkedAt: null, error: null });
  const [escalationOpen, setEscalationOpen] = useState(false);
  const [escalationIncidentId, setEscalationIncidentId] = useState<string | null>(null);
  const [escalationBuyerToken, setEscalationBuyerToken] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [isThinking, setIsThinking] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatBodyRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [cvPrefillImages, setCvPrefillImages] = useState<File[]>([]);
  const [pendingImageContext, setPendingImageContext] = useState<PendingImageContext | null>(null);
  const [imageRoutingInFlight, setImageRoutingInFlight] = useState(false);
  const [lastCvSecurityNoteKey, setLastCvSecurityNoteKey] = useState<string | null>(null);
  const uid = (localStorage.getItem('uid') || 'demo-user');
  const [cart, setCart] = useState<any | null>(null);

  // Multimodal: attached images queued for Send
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [attachedThumbs, setAttachedThumbs] = useState<string[]>([]);

  // Dual STT (browser + Whisper)
  const stt = useDualSTT();

  // Sync STT transcript into input
  useEffect(() => {
    if (stt.transcript) setInputValue(stt.transcript);
  }, [stt.transcript]);

  /** Add files from AttachmentButton / drop / paste */
  const handleAttach = useCallback((files: File[]) => {
    const imgFiles = files.filter(f => f.type.startsWith('image/'));
    if (imgFiles.length === 0) return;
    setAttachedFiles(prev => [...prev, ...imgFiles]);
    // Generate thumbnails as data URLs
    imgFiles.forEach(f => {
      const reader = new FileReader();
      reader.onload = () => setAttachedThumbs(prev => [...prev, reader.result as string]);
      reader.readAsDataURL(f);
    });
  }, []);

  const removeAttachment = useCallback((idx: number) => {
    setAttachedFiles(prev => prev.filter((_, i) => i !== idx));
    setAttachedThumbs(prev => prev.filter((_, i) => i !== idx));
  }, []);

  const maybeAppendCvSecurityNote = (cvResult: any) => {
    if (!cvResult || typeof cvResult !== 'object') return;

    const tags = Array.isArray(cvResult.evidence_tags) ? cvResult.evidence_tags.map(String) : [];
    const ic = (cvResult.image_consistency && typeof cvResult.image_consistency === 'object') ? cvResult.image_consistency : null;

    const reasons = new Set<string>();
    try {
      const imgs = Array.isArray(ic?.images) ? ic.images : [];
      for (const it of imgs) {
        const rs = Array.isArray(it?.reasons) ? it.reasons : [];
        rs.forEach((r: any) => reasons.add(String(r)));
      }
    } catch {
      // ignore
    }

    const hasQr = tags.includes('qr_url_present') || tags.includes('ocr_prompt_injection') || reasons.has('qr_code_detected') || reasons.has('qr_external_url_detected') || Boolean(cvResult.qr_prompt_injection);
    const hasManipulation = tags.includes('manipulation_detected') || reasons.has('manipulation_detected');
    const hasPromptInjection = tags.includes('prompt_injection_text_suspected') || tags.includes('ocr_prompt_injection') || reasons.has('ocr_prompt_pattern_detected');
    if (!hasQr && !hasManipulation && !hasPromptInjection) return;

    const noteKey = String(cvResult.case_id || cvResult.trace_id || cvResult.decision_id || '') + `|qr=${hasQr}|manip=${hasManipulation}|pi=${hasPromptInjection}`;
    if (noteKey && noteKey === lastCvSecurityNoteKey) return;

    const parts: string[] = [];
    if (hasQr) parts.push('a QR code or external link');
    if (hasManipulation) parts.push('signs the photo may be edited or altered');
    if (hasPromptInjection && !hasQr) parts.push('embedded text that resembles an instruction or command');

    const what = parts.length === 2 ? `${parts[0]} and ${parts[1]}` : parts[0];
    const msg =
      `Security note: One of your photos appears to include ${what}.\n\n` +
      `For your safety, we do not follow links or accept photos with added overlays for verification. ` +
      `Please re-upload a new, unedited photo of the item and the damage (no stickers, text overlays, or QR codes).`;

    setLastCvSecurityNoteKey(noteKey || null);
    setMessages(prev => [...prev, { role: 'assistant', content: msg, timestamp: new Date() }]);
  };

  const refreshCart = async () => {
    try {
      const j = await getCart(uid);
      setCart(j);
    } catch {
      setCart(null);
    }
  };

  const addToCart = async (sku: string) => {
    if (!sku) return;
    try {
      const j = await addCartItem(uid, sku, 1);
      setCart(j);
      setRightPanelMode('cart');
    } catch {
      // ignore for MVP
    }
  };

  const removeFromCart = async (sku: string) => {
    if (!sku) return;
    try {
      const j = await removeCartItem(uid, sku);
      setCart(j);
    } catch {
      // ignore
    }
  };

  const clearCartAll = async () => {
    try {
      const j = await clearCart(uid);
      setCart(j);
    } catch {
      // ignore
    }
  };

  const handleCameraCapture = async (files: File[]) => {
    if (!files || files.length === 0) return;
    // Defer triage until Send — just attach thumbnails
    handleAttach(files);
    setCvPrefillImages(files);
  };

  // Microphone handler — delegates to dual STT hook
  const handleMicClick = () => {
    if (stt.error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Speech recognition is not supported in your browser. Please try Chrome or Edge for voice input.',
        timestamp: new Date()
      }]);
      return;
    }
    stt.toggle();
  };

  const hasRightPanel = rightPanelMode !== 'none';

  const normalizeNextQuestions = (items: any[]): { id: string; text: string; goal?: string }[] => {
    if (!Array.isArray(items)) return [];
    const out = items
      .map((item: any, idx: number) => {
        if (item && typeof item === 'object') {
          const text = String(item.text || item.question || '').trim();
          if (!text) return null;
          return {
            id: String(item.id || `nq_${idx + 1}`),
            text,
            goal: item.goal ? String(item.goal) : undefined,
          };
        }
        const text = String(item || '').trim();
        if (!text) return null;
        return { id: `nq_${idx + 1}`, text };
      })
      .filter(Boolean) as { id: string; text: string; goal?: string }[];
    return out.slice(0, 3);
  };

  const formatNextQuestions = (items: any[]): string => {
    if (!Array.isArray(items) || items.length === 0) return '';
    const lines = items
      .map((item: any) => {
        if (item && typeof item === 'object') return String(item.text || item.question || '').trim();
        return String(item || '').trim();
      })
      .filter(Boolean)
      .slice(0, 3);
    if (lines.length === 0) return '';
    return `\n\nTo narrow this down quickly:\n- ${lines.join('\n- ')}`;
  };

  const complaintTextHint = (text: string) => /\b(return|broken|damaged|refund|complaint|defective|wrong item|warranty)\b/i.test(text || '');
  const visualSearchHint = (text: string) => /\b(find similar|similar products?|visual search|look like this|like this|match this)\b/i.test(text || '');

  const summarizeWhy = (items: Product[]) => {
    if (!Array.isArray(items) || items.length === 0) return '';
    const snippets = items
      .slice(0, 2)
      .map((p) => {
        const why = Array.isArray(p.why) ? p.why.filter(Boolean).slice(0, 2) : [];
        if (!p?.name || why.length === 0) return '';
        return `${p.name} (${why.join(', ')})`;
      })
      .filter(Boolean);
    return snippets.length > 0 ? `Top picks: ${snippets.join('; ')}.` : '';
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Lock body scroll when overlay is open
  useEffect(() => {
    if (chatOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [chatOpen]);

  // Lightweight backend liveness indicator (dev UX). Uses Vite proxy for /healthz.
  useEffect(() => {
    if (!chatOpen) return;
    let mounted = true;
    let iv: any = null;

    const ping = async () => {
      const ctl = new AbortController();
      const t0 = performance.now();
      const to = setTimeout(() => ctl.abort(), 2500);
      try {
        const r = await fetch(apiUrl('/healthz'), { signal: ctl.signal });
        const ms = Math.round(performance.now() - t0);
        if (!mounted) return;
        setBackendStatus({ ok: r.ok, latencyMs: ms, checkedAt: new Date(), error: r.ok ? null : `http_${r.status}` });
      } catch (e: any) {
        const ms = Math.round(performance.now() - t0);
        if (!mounted) return;
        setBackendStatus({ ok: false, latencyMs: ms, checkedAt: new Date(), error: e?.name === 'AbortError' ? 'timeout' : (e?.message || 'fetch_failed') });
      } finally {
        clearTimeout(to);
      }
    };

    ping();
    iv = setInterval(ping, 5000);
    return () => {
      mounted = false;
      if (iv) clearInterval(iv);
    };
  }, [chatOpen]);

  const handleSend = async () => {
    const q = inputValue.trim();
    if (!q) return;

    // PII Detection - warn user and don't send sensitive data
    const pii = detectPII(q);
    if (pii) {
      const userMsg: ChatMessage = { role: 'user', content: q.replace(/\d/g, '*'), timestamp: new Date() };
      const warningMsg: ChatMessage = {
        role: 'assistant',
        content: `I noticed you may have entered a ${pii.type}. ${pii.advice}\n\nYour message was not sent to protect your privacy. Please rephrase without sensitive information.`,
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, userMsg, warningMsg]);
      setInputValue('');
      return;
    }

    const userMsg: ChatMessage = { role: 'user', content: q, timestamp: new Date(), images: [...attachedThumbs], voiceUsed: stt.source !== null };
    setMessages(prev => [...prev, userMsg]);
    setInputValue('');
    const currentAttachedFiles = [...attachedFiles];
    const currentSttConf = stt.whisperConfidence;
    const currentSttSrc = stt.source;
    setAttachedFiles([]);
    setAttachedThumbs([]);
    setIsThinking(true);

    const mode = detectPanelMode(q);
    const complaintIntent = isComplaintIntent(q);
    const hasImages = currentAttachedFiles.length > 0;
    const hasPendingImage = Boolean(pendingImageContext) || cvPrefillImages.length > 0 || hasImages;
    const explicitVisualIntent = visualSearchHint(q);
    const explicitComplaintIntent = complaintTextHint(q);
    const requestImageContext = (Boolean(pendingImageContext) && !explicitComplaintIntent) ? pendingImageContext : null;

    if (hasPendingImage && explicitComplaintIntent && !hasImages) {
      setPendingImageContext(null);
      setRightPanelMode('cv');
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Opening return/complaint flow with your uploaded photo.',
        timestamp: new Date(),
      }]);
      setIsThinking(false);
      return;
    }

    if (requestImageContext) {
      setPendingImageContext(null);
      if (explicitVisualIntent) {
        setCvPrefillImages([]);
      }
    }

    // Call backend
    try {
      // If images are attached, triage them first
      let imageTriageResults: any[] = [];
      if (hasImages) {
        setImageRoutingInFlight(true);
        try {
          const triagePromises = currentAttachedFiles.map(async (file) => {
            const fd = new FormData();
            fd.append('image', file);
            const r = await fetch(apiUrl('/api/v1/vision/triage'), {
              method: 'POST',
              body: fd,
              headers: { 'x-api-key': ((import.meta as any).env?.VITE_API_KEY || '') },
            });
            return r.ok ? await safeJson(r) : null;
          });
          imageTriageResults = (await Promise.all(triagePromises)).filter(Boolean);
        } finally {
          setImageRoutingInFlight(false);
        }

        // Auto-route to CV if damage detected
        const anyDamage = imageTriageResults.some((t: any) => {
          const ds = t?.damage_score ?? 0;
          return ds >= 0.7;
        });
        if (anyDamage && (explicitComplaintIntent || complaintIntent)) {
          setCvPrefillImages(currentAttachedFiles);
          setRightPanelMode('cv');
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: 'I detected likely damage in your photo and opened the return/complaint panel.',
            timestamp: new Date(),
          }]);
          setIsThinking(false);
          return;
        }
      }

      const routeToComplaint = (mode === 'cv' || complaintIntent || explicitComplaintIntent) && !explicitVisualIntent && !requestImageContext && !hasImages;
      if (routeToComplaint) {
        const r = await fetch(apiUrl('/api/v1/orchestrate'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-api-key': ((import.meta as any).env?.VITE_API_KEY || '') },
          body: JSON.stringify({
            uid: localStorage.getItem('uid') || 'demo-user',
            cart_total_cents: 0,
            query: q,
            complaint_intent: true,
          }),
        });
        const data = await safeJson(r);
        if (!r.ok || !data) {
          throw new Error((data && data.detail) ? data.detail : `orchestrate_failed (${r.status})`);
        }
        const proposal = data.proposal || {};
        const results = (proposal.results || []) as any[];
        const prods = results.map((item) => {
          const price = item.price_cents ? item.price_cents / 100 : item.price;
          const specs = item.specs || {};
          const features = [
            specs.cpu,
            specs.ram_gb ? `${specs.ram_gb}GB RAM` : undefined,
            specs.storage,
            specs.display,
            specs.wifi,
          ].filter(Boolean) as string[];
          return {
            sku: item.sku,
            name: item.name,
            price: price ?? 0,
            features,
            image_url: item.image_url,
          } as Product;
        });
        setTraceId(data.decision_trace_id || data.trace_id || proposal.trace_id || null);
        if (prods.length > 0) {
          setDisplayProducts(prods);
          setRightPanelMode('cv');
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: `I've started a return review. I also found ${prods.length} related items if you want comparisons.`,
            timestamp: new Date(),
          };
          setMessages(prev => [...prev, assistantMsg]);
        } else {
          setRightPanelMode('cv');
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: "I've started a return review. Please add photos if you have them.",
            timestamp: new Date(),
          };
          setMessages(prev => [...prev, assistantMsg]);
        }
      } else {
        // Build multimodal chat payload
        const chatPayload: any = { uid, query: q };
        if (currentSttSrc) {
          chatPayload.voice_transcript = q;
          chatPayload.voice_confidence = currentSttConf ?? undefined;
        }
        // Attach image triage data
        if (imageTriageResults.length > 0) {
          chatPayload.images = imageTriageResults.map((t: any) => ({
            labels: t?.labels || [],
            ocr_text: t?.extracted_text || '',
            image_hash: t?.image_hash || null,
            damage_score: t?.damage_score ?? 0,
            is_product_photo: t?.is_product_photo ?? false,
            intent_routing: t?.intent_routing || null,
            security: t?.security || null,
          }));
        } else if (requestImageContext) {
          chatPayload.image_labels = requestImageContext.labels || [];
          chatPayload.image_ocr_text = requestImageContext.ocrText || '';
          chatPayload.image_hash = requestImageContext.imageHash || undefined;
          chatPayload.image_intent = 'visual_search';
        }
        chatPayload.recent_messages = messages.slice(-6).map(m => ({ role: m.role, content: m.content }));

        const r = await fetch(apiUrl('/api/v1/chat/query'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-api-key': ((import.meta as any).env?.VITE_API_KEY || '') },
          body: JSON.stringify(chatPayload),
        });
        const data = await safeJson(r);
        if (!r.ok || !data) {
          throw new Error((data && data.detail) ? data.detail : `chat_query_failed (${r.status})`);
        }
        const prods = (data.products || []) as Product[];
        const respAssistant = data.assistant_message || '';
        const nextQuestions = Array.isArray(data.next_questions) ? data.next_questions : [];
        const normalizedNextQuestions = normalizeNextQuestions(nextQuestions);
        const isDisambiguation = data.disambiguation === true;
        const disambiguationOpts = Array.isArray(data.next_questions) ? data.next_questions.map((nq: any) => typeof nq === 'string' ? nq : nq?.text || '') : [];
        const complexity = data.complexity || null;
        setTraceId(data.decision_trace_id || null);

        if (isDisambiguation) {
          // Show disambiguation buttons instead of products
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: respAssistant || 'I see you uploaded an image. What would you like to do?',
            timestamp: new Date(),
            disambiguation: true,
            disambiguationOptions: disambiguationOpts,
            complexity,
          };
          setMessages(prev => [...prev, assistantMsg]);
        } else if (prods.length > 0) {
          const visibleProducts = prods.slice(0, 12);
          setDisplayProducts(visibleProducts);
          setRightPanelMode(mode === 'none' ? 'grid' : mode);
          const whySummary = summarizeWhy(prods);
          const hasAssistantBody = typeof respAssistant === 'string' && respAssistant.trim().length > 0;
          const baseLine = hasAssistantBody
            ? respAssistant.trim()
            : `I found ${prods.length} ${mode === 'compare' ? 'products to compare' : 'matching products'} and I’m showing the top ${visibleProducts.length}.`;
          const includeWhy = whySummary && !/top picks:/i.test(baseLine);

          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: `${baseLine}${includeWhy ? `\n\n${whySummary}` : ''}`,
            timestamp: new Date(),
            complexity,
            nextQuestions: normalizedNextQuestions,
          };
          setMessages(prev => [...prev, assistantMsg]);
        } else {
          setRightPanelMode(mode);
          const nqePrompt = formatNextQuestions(nextQuestions);
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: (respAssistant || 'I could not find products matching that query.') + nqePrompt,
            timestamp: new Date(),
            complexity,
            nextQuestions: normalizedNextQuestions,
          };
          setMessages(prev => [...prev, assistantMsg]);
        }
      }
    } catch (e: any) {
      setTraceId(null);
      setRightPanelMode('none');
      const errMsg = (e && (e.message || String(e))) ? (e.message || String(e)) : 'unknown_error';
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Backend unavailable. Decision Trace was not recorded.\n\nTroubleshooting:\n- Confirm FastAPI is running (default: http://127.0.0.1:8080).\n- Vite proxy should forward /api to the backend.\n- Error: ${errMsg}`,
        timestamp: new Date(),
      }]);
      return;
    } finally {
      setIsThinking(false);
    }
  };

  const handleQuickAction = (query: string) => {
    setInputValue(query);
    setTimeout(() => handleSend(), 100);
  };

  /** Disambiguation button click → re-send with the chosen intent */
  const handleDisambiguationSelect = (option: string) => {
    setInputValue(option);
    setTimeout(() => handleSend(), 100);
  };

  /** Drag-and-drop on chat body */
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files);
    handleAttach(files);
  }, [handleAttach]);

  /** Paste images in chat body */
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = Array.from(e.clipboardData.items);
    const files: File[] = [];
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      handleAttach(files);
    }
  }, [handleAttach]);

  /** Auto-resize textarea */
  const handleTextareaInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }, []);

  return (
    <div className={styles.page}>
      {/* Homepage Header */}
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <div className={styles.logo}>Shop<span>Squire</span></div>
          <div className={styles.searchBox}>
            <input type="text" placeholder="Search products..." className={styles.searchInput} />
            <button className={styles.searchBtn}>Search</button>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.headerBtn} onClick={() => { refreshCart(); setRightPanelMode('cart'); }}>
              Cart ({(cart?.items || []).length || 0})
            </button>
            <button className={styles.headerBtn}>Login</button>
          </div>
        </div>
      </header>

      {/* Homepage Product Grid */}
      <main className={styles.main}>
        <div className={styles.categoryBar}>
          <span className={styles.categoryTitle}>Laptops</span>
          <div className={styles.filters}>
            <button className={styles.filterBtn}>Price</button>
            <button className={styles.filterBtn}>RAM</button>
            <button className={styles.filterBtn}>Brand</button>
            <button className={styles.filterBtn}>GPU</button>
          </div>
        </div>
        <ProductGrid products={products} onAdd={addToCart} viewMode="grid" />
      </main>

      {/* Floating Chat Button */}
      {!chatOpen && (
        <button className={styles.chatFab} onClick={() => setChatOpen(true)}>
          <ChatIcon />
          <span className={styles.fabLabel}>Ask Me!</span>
        </button>
      )}

      {/* Chat Overlay */}
      {chatOpen && (
        <div className={styles.overlay}>
          <div className={`${styles.chatContainer} ${hasRightPanel ? styles.withPanel : ''}`}>
            {/* Chat Panel */}
            <div className={styles.chatPanel}>
              <div className={styles.chatHeader}>
                <div className={styles.chatHeaderLeft}>
                  <span className={styles.chatTitle}>ShopSquire Assistant</span>
                  <span
                    className={`${styles.backendPill} ${backendStatus.ok ? styles.backendUp : styles.backendDown}`}
                    title={
                      backendStatus.checkedAt
                        ? `Backend: ${backendStatus.ok ? 'UP' : 'DOWN'}${backendStatus.latencyMs != null ? ` (${backendStatus.latencyMs}ms)` : ''}${backendStatus.error ? ` | ${backendStatus.error}` : ''}`
                        : 'Backend: unknown'
                    }
                  >
                    <span className={styles.backendDot} />
                    {backendStatus.ok ? `API ${backendStatus.latencyMs != null ? `${backendStatus.latencyMs}ms` : 'up'}` : 'API down'}
                  </span>
                </div>
                <div className={styles.chatHeaderActions}>
                  <button
                    className={styles.iconBtn}
                    onClick={() => setTraceOpen(true)}
                    title={traceId ? 'Decision Trace' : 'Decision Trace (opens after a routed decision creates a trace id)'}
                    aria-label="Decision Trace"
                  >
                    <GearIcon />
                  </button>
                  <button className={styles.iconBtn} title="Pop-out"><DetachIcon /></button>
                  <button className={styles.iconBtn} onClick={() => { setChatOpen(false); setRightPanelMode('none'); }} title="Close"><CloseIcon /></button>
                </div>
              </div>

              <div
                className={styles.chatBody}
                ref={chatBodyRef}
                onDrop={handleDrop}
                onDragOver={(e) => e.preventDefault()}
                onPaste={handlePaste}
              >
                {messages.length === 0 && (
                  <div className={styles.welcome}>
                    <p>Hi! I'm your ShopSquire assistant.</p>
                    <p>Ask me about laptops, compare models, or get recommendations.</p>
                    <p className={styles.welcomeHint}>You can also paste or drag images into this chat.</p>
                    <div className={styles.quickActions}>
                      <button onClick={() => handleQuickAction('Show gaming laptops under $2000')}>Gaming</button>
                      <button onClick={() => handleQuickAction('Budget laptops under $1000')}>Budget</button>
                      <button onClick={() => handleQuickAction('Compare top MacBooks')}>Compare</button>
                      <button onClick={() => handleQuickAction('Show detailed specs for workstations')}>Specs</button>
                    </div>
                  </div>
                )}
                {messages.map((msg, i) => (
                  <div key={i} className={`${styles.message} ${styles[msg.role]}`}>
                    <div className={styles.messageContent}>
                      {/* Inline image thumbnails for user messages */}
                      {msg.images && msg.images.length > 0 && (
                        <div className={styles.msgImageStrip}>
                          {msg.images.map((src, j) => (
                            <img key={j} src={src} alt={`attachment ${j + 1}`} className={styles.msgThumb} />
                          ))}
                        </div>
                      )}
                      {msg.content}
                      {/* Voice badge */}
                      {msg.voiceUsed && <span className={styles.voiceBadge} title="Sent via voice">🎤</span>}
                      {/* Complexity badge */}
                      {msg.complexity && (
                        <span className={styles.complexityBadge} title={`Tier: ${msg.complexity.tier} | Model: ${msg.complexity.model}`}>
                          ⚡ {msg.complexity.score}/10
                        </span>
                      )}
                      {msg.nextQuestions && msg.nextQuestions.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
                          {msg.nextQuestions.map((nq) => (
                            <button
                              key={nq.id}
                              type="button"
                              className={styles.filterBtn}
                              onClick={() => handleQuickAction(nq.text)}
                            >
                              {nq.text}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    {/* Disambiguation buttons for assistant */}
                    {msg.disambiguation && msg.disambiguationOptions && msg.disambiguationOptions.length > 0 && (
                      <DisambiguationButtons options={msg.disambiguationOptions} onSelect={handleDisambiguationSelect} />
                    )}
                  </div>
                ))}
                {(isThinking || imageRoutingInFlight) && (
                  <div className={`${styles.message} ${styles.assistant}`}>
                    <div className={`${styles.messageContent} ${styles.thinkingBubble}`}>
                      <span className={styles.thinkingDot}>.</span>
                      <span className={styles.thinkingDot}>.</span>
                      <span className={styles.thinkingDot}>.</span>
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Composer Card */}
              <div className={styles.chatFooter}>
                {/* Thumbnail strip for attached images */}
                {attachedThumbs.length > 0 && (
                  <div className={styles.thumbStrip}>
                    {attachedThumbs.map((src, i) => (
                      <div key={i} className={styles.thumbWrap}>
                        <img src={src} alt={`attached ${i + 1}`} className={styles.thumbImg} />
                        <button className={styles.thumbRemove} onClick={() => removeAttachment(i)} title="Remove">&times;</button>
                      </div>
                    ))}
                  </div>
                )}
                <div className={styles.composerRow}>
                  <AttachmentButton onFiles={handleAttach} className={styles.inputIconBtn} />
                  <textarea
                    ref={textareaRef}
                    className={styles.chatInput}
                    placeholder={imageRoutingInFlight ? "Analyzing image..." : (stt.isRecording ? "Listening..." : "Type your message...")}
                    value={inputValue}
                    onChange={(e) => { setInputValue(e.target.value); handleTextareaInput(); }}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                    rows={1}
                  />
                  <button
                    className={`${styles.inputIconBtn} ${stt.isRecording ? styles.recording : ''}`}
                    onClick={handleMicClick}
                    title={stt.isRecording ? 'Click to stop recording' : 'Voice input'}
                  >
                    <MicIcon />
                    {stt.whisperPending && <span className={styles.whisperDot} />}
                  </button>
                  <button className={styles.sendBtn} onClick={handleSend} disabled={isThinking || imageRoutingInFlight}><SendIcon /></button>
                </div>
              </div>
            </div>

            {/* Right Panel */}
            {hasRightPanel && (
              <div className={styles.rightPanel}>
                <div className={styles.rightHeader}>
                  <span>
                    {rightPanelMode === 'compare'
                      ? 'Comparison'
                      : rightPanelMode === 'list'
                        ? 'Detailed Specs'
                        : rightPanelMode === 'cv'
                          ? 'CV Triage'
                          : rightPanelMode === 'cart'
                            ? 'Cart & Upsell'
                            : rightPanelMode === 'visual_search'
                              ? 'Visual Search'
                              : rightPanelMode === 'image_context'
                                ? 'Image Context'
                                : `Found ${displayProducts.length} products`}
                  </span>
                  <div className={styles.viewToggle}>
                    <button className={viewMode === 'grid' ? styles.active : ''} onClick={() => setViewMode('grid')}><GridIcon /></button>
                    <button className={viewMode === 'list' ? styles.active : ''} onClick={() => setViewMode('list')}><ListIcon /></button>
                  </div>
                </div>
                <div className={styles.rightBody}>
                  {rightPanelMode === 'faq' ? (
                    <RightPanelExtras mode="faq" />
                  ) : rightPanelMode === 'visual_search' ? (
                    <RightPanelExtras mode="visual_search" />
                  ) : rightPanelMode === 'image_context' ? (
                    <RightPanelExtras mode="image_context" />
                  ) : rightPanelMode === 'cv' ? (
                    <RightPanelExtras
                      mode="cv"
                      initialImages={cvPrefillImages}
                      onEscalate={(payload) => {
                        const incId = payload?.incident_id;
                        if (!incId) {
                          setMessages(prev => [...prev, {
                            role: 'assistant',
                            content: 'Escalation failed: incident id was not returned by /api/v1/incidents/escalate.',
                            timestamp: new Date(),
                          }]);
                          return;
                        }
                        setEscalationIncidentId(incId);
                        if (payload?.buyer_token) setEscalationBuyerToken(String(payload.buyer_token)); else setEscalationBuyerToken(null);
                        setEscalationOpen(true);
                        setMessages(prev => [...prev, { role: 'assistant', content: 'Escalated to human review. Opening escalation room...', timestamp: new Date() }]);
                      }}
                      onTraceId={(tid) => setTraceId(tid)}
                      onResult={(cvRes: any) => {
                        setCvPrefillImages([]);
                        maybeAppendCvSecurityNote(cvRes);
                      }}
                    />
                  ) : rightPanelMode === 'compare' && displayProducts.length > 0 ? (
                    <div className={styles.compareTable}>
                      <table>
                        <thead>
                          <tr>
                            <th>Feature</th>
                            {displayProducts.slice(0, 3).map(p => <th key={p.sku}>{p.name.split(' ').slice(0, 3).join(' ')}</th>)}
                          </tr>
                        </thead>
                        <tbody>
                          <tr><td>Price</td>{displayProducts.slice(0, 3).map(p => <td key={p.sku}>${p.price.toLocaleString()}</td>)}</tr>
                          {['Display', 'Processor', 'RAM', 'Storage', 'Graphics'].map((feat, i) => (
                            <tr key={feat}>
                              <td>{feat}</td>
                              {displayProducts.slice(0, 3).map(p => <td key={p.sku}>{(p.features || [])[i + 1]?.replace(/^[^:]+:\s*/, '') || '-'}</td>)}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    rightPanelMode === 'cart' ? (
                      <CartPanel
                        uid={uid}
                        cart={cart}
                        onRefresh={refreshCart}
                        onRemove={removeFromCart}
                        onClear={clearCartAll}
                        onAdd={addToCart}
                        onTraceId={(tid) => setTraceId(tid)}
                      />
                    ) : (
                      <ProductGrid
                        products={displayProducts}
                        onAdd={addToCart}
                        viewMode={viewMode === 'list' || rightPanelMode === 'list' ? 'detailed' : 'grid'}
                      />
                    )
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Decision Trace Modal */}
      {traceOpen && <DecisionTrace traceId={traceId} onClose={() => setTraceOpen(false)} />}

      {/* Escalation Room Modal */}
      {escalationOpen && escalationIncidentId && (
        <EscalationRoom incidentId={escalationIncidentId} buyerToken={escalationBuyerToken} onClose={() => setEscalationOpen(false)} />
      )}
    </div>
  );
}
