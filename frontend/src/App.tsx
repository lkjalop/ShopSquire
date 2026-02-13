import { useEffect, useMemo, useState, useRef } from 'react';
import styles from './App.module.css';
import ProductGrid from './components/ProductGrid';
import DecisionTrace from './components/DecisionTrace';
import EscalationRoom from './components/EscalationRoom';
import RightPanelExtras from './components/RightPanelExtras';
import { apiUrl, safeJson, getCart, addCartItem, removeCartItem, clearCart } from './lib/api';
import CameraButton from './components/CameraButton';
import CartPanel from './components/CartPanel';

export type Product = {
  sku: string;
  name: string;
  price: number;
  features?: string[];
  image_url?: string;
  why?: string[];
  score_norm?: number;
};
type RightPanelMode = 'none' | 'grid' | 'list' | 'compare' | 'cv' | 'cart' | 'faq' | 'security';
type ChatMessage = { role: 'user' | 'assistant'; content: string; timestamp: Date };


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
    if (digits.length >= 13 && digits.length <= 19 && luhnCheck(digits)) {
      return {
        type: 'credit card number',
        advice: 'Never share payment card details in chat. Use our secure checkout instead.'
      };
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
  const [escalationOpen, setEscalationOpen] = useState(false);
  const [escalationIncidentId, setEscalationIncidentId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [isRecording, setIsRecording] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const [cvPrefillImages, setCvPrefillImages] = useState<File[]>([]);
  const uid = (localStorage.getItem('uid') || 'demo-user');
  const [cart, setCart] = useState<any | null>(null);

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

  const handleCameraCapture = (files: File[]) => {
    if (!files || files.length === 0) return;
    setCvPrefillImages(files);
    setRightPanelMode('cv');
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: 'Photo(s) attached. Fill in the complaint details on the right panel and submit for CV triage.',
      timestamp: new Date()
    }]);
  };

  // Microphone handler - speech-to-text
  const handleMicClick = async () => {
    const SpeechRecognitionAPI = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (!SpeechRecognitionAPI) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Speech recognition is not supported in your browser. Please try Chrome or Edge for voice input.',
        timestamp: new Date()
      }]);
      return;
    }

    if (isRecording) {
      setIsRecording(false);
      return;
    }

    const recognition = new SpeechRecognitionAPI();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setInputValue(transcript);
      setIsRecording(false);
    };

    recognition.onerror = () => setIsRecording(false);
    recognition.onend = () => setIsRecording(false);

    setIsRecording(true);
    recognition.start();
  };

  const hasRightPanel = rightPanelMode !== 'none';

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

    const userMsg: ChatMessage = { role: 'user', content: q, timestamp: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setInputValue('');
    setIsThinking(true);

    const mode = detectPanelMode(q);
    const complaintIntent = isComplaintIntent(q);

    // Call backend
    try {
      if (mode === 'cv' || complaintIntent) {
        const r = await fetch(apiUrl('/api/v1/orchestrate'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' },
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
        const r = await fetch(apiUrl('/api/v1/chat/query'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' },
          body: JSON.stringify({ query: q }),
        });
        const data = await safeJson(r);
        if (!r.ok || !data) {
          throw new Error((data && data.detail) ? data.detail : `chat_query_failed (${r.status})`);
        }
        const prods = (data.products || []) as Product[];
        const respAssistant = data.assistant_message || '';
        const nextQuestions = Array.isArray(data.next_questions) ? data.next_questions : [];
        setTraceId(data.decision_trace_id || null);
        if (prods.length > 0) {
          setDisplayProducts(prods);
          setRightPanelMode(mode === 'none' ? 'grid' : mode);

          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: `Found ${prods.length} ${mode === 'compare' ? 'products to compare' : 'matching products'}. ${respAssistant}`,
            timestamp: new Date(),
          };
          setMessages(prev => [...prev, assistantMsg]);
        } else {
          setRightPanelMode(mode);
          const nqePrompt = formatNextQuestions(nextQuestions);
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: (respAssistant || 'I could not find products matching that query.') + nqePrompt,
            timestamp: new Date(),
          };
          setMessages(prev => [...prev, assistantMsg]);
        }
      }
    } catch {
      setTraceId(null);
      setRightPanelMode('none');
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Backend unavailable. Decision Trace was not recorded. Please check the API connection and try again.',
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
                <span className={styles.chatTitle}>ShopSquire Assistant</span>
                <div className={styles.chatHeaderActions}>
                  <button
                    className={styles.iconBtn}
                    onClick={() => traceId && setTraceOpen(true)}
                    title={traceId ? 'Decision Trace' : 'Decision Trace (available after first routed decision)'}
                    disabled={!traceId}
                    aria-label="Decision Trace"
                  >
                    <GearIcon />
                  </button>
                  <button className={styles.iconBtn} title="Pop-out"><DetachIcon /></button>
                  <button className={styles.iconBtn} onClick={() => { setChatOpen(false); setRightPanelMode('none'); }} title="Close"><CloseIcon /></button>
                </div>
              </div>

              <div className={styles.chatBody}>
                {messages.length === 0 && (
                  <div className={styles.welcome}>
                    <p>Hi! I'm your ShopSquire assistant.</p>
                    <p>Ask me about laptops, compare models, or get recommendations.</p>
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
                    <div className={styles.messageContent}>{msg.content}</div>
                  </div>
                ))}
                {isThinking && (
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

              <div className={styles.chatFooter}>
                <CameraButton onFiles={handleCameraCapture} className={styles.inputIconBtn} />
                <input
                  type="text"
                  className={styles.chatInput}
                  placeholder={isRecording ? "Listening..." : "Type your message..."}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                />
                <button
                  className={`${styles.inputIconBtn} ${isRecording ? styles.recording : ''}`}
                  onClick={handleMicClick}
                  title={isRecording ? 'Click to stop recording' : 'Voice input'}
                >
                  <MicIcon />
                </button>
                <button className={styles.sendBtn} onClick={handleSend}><SendIcon /></button>
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
                  ) : rightPanelMode === 'cv' ? (
                    <RightPanelExtras
                      mode="cv"
                      initialImages={cvPrefillImages}
                      onEscalate={(payload) => {
                        const incId = payload?.case_id || payload?.decision_id || 'incident-demo';
                        setEscalationIncidentId(incId);
                        setEscalationOpen(true);
                        setMessages(prev => [...prev, { role: 'assistant', content: 'Escalated to human review. Opening escalation room...', timestamp: new Date() }]);
                      }}
                      onTraceId={(tid) => setTraceId(tid)}
                      onResult={() => setCvPrefillImages([])}
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
      {traceOpen && traceId && <DecisionTrace traceId={traceId} onClose={() => setTraceOpen(false)} />}

      {/* Escalation Room Modal */}
      {escalationOpen && escalationIncidentId && (
        <EscalationRoom incidentId={escalationIncidentId} onClose={() => setEscalationOpen(false)} />
      )}
    </div>
  );
}
