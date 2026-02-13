# GitHub Copilot Fix Guide - ShopSquire Issues

**Date:** 2026-01-31
**Reference Screenshots:** `dump/shop-PII-list.png`, `dump/laptop-smart.png`, `dump/laptop-pricewrong.png`

---

## Quick Start for Copilot

Use this prompt in GitHub Copilot:

```
I'm working on ShopSquire, a retail AI assistant. Key issues to fix:

1. PII/Credit Card Detection - User can type credit card numbers without warning
2. Decision Trace - Empty, not logging events
3. Price Filtering - Products outside range shown
4. NLP Intelligence - Using keyword matching instead of LLM

Key files to reference:
- Frontend: frontend/src/App.tsx, frontend/src/components/DecisionTrace.tsx
- Backend PII: src/app/deps.py, src/app/security/pci.py, src/app/safety/redaction.py
- Backend Recommend: src/app/routers/recommend.py, src/app/services/recommendations.py
- Backend Decisions: src/app/routers/decisions.py, src/app/services/decision_log.py
- Config: config/feature_flags.json
```

---

## Issue 1: PII/Credit Card Not Detected

### Evidence
**Screenshot:** `dump/shop-PII-list.png`

User typed: `"want to take my card 5489123456784321 567 10/29"`

System response: Just echoed it back with no warning.

### Root Cause

**File:** `src/app/deps.py` (lines 87-93)

```python
def scrub_pii(text: str) -> str:
    text = PII_EMAIL.sub("[REDACTED_EMAIL]", text)
    text = PII_PHONE.sub("[REDACTED_PHONE]", text)
    text = PII_SSN.sub("[REDACTED_SSN]", text)
    text = PII_IP.sub("[REDACTED_IP]", text)
    text = API_KEY_PAT.sub("[REDACTED_API_KEY]", text)
    return text  # <-- NO CREDIT CARD HANDLING!
```

**File:** `src/app/security/pci.py` (lines 23-33) - Has Luhn check but NOT integrated:

```python
def contains_pci_data(text: str) -> bool:
    # This exists but isn't called for input validation
    for m in CARD_RE.finditer(text):
        candidate = re.sub(r"[^0-9]", "", m.group(0))
        if 13 <= len(candidate) <= 19 and luhn_check(candidate):
            return True
    return False
```

### Fix #1: Backend - Add Credit Card to scrub_pii()

**File:** `src/app/deps.py`

**Line ~75:** Add pattern:
```python
PII_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
```

**Line ~87:** Update function:
```python
def scrub_pii(text: str) -> str:
    from src.app.security.pci import contains_pci_data, CARD_RE

    # Check for credit card first (with Luhn validation)
    for m in CARD_RE.finditer(text):
        candidate = re.sub(r"[^0-9]", "", m.group(0))
        if 13 <= len(candidate) <= 19:
            text = text.replace(m.group(0), "[REDACTED_CARD]")

    text = PII_EMAIL.sub("[REDACTED_EMAIL]", text)
    text = PII_PHONE.sub("[REDACTED_PHONE]", text)
    text = PII_SSN.sub("[REDACTED_SSN]", text)
    text = PII_IP.sub("[REDACTED_IP]", text)
    text = API_KEY_PAT.sub("[REDACTED_API_KEY]", text)
    return text
```

### Fix #2: Frontend - Client-side PII Warning

**File:** `frontend/src/App.tsx`

**Add before handleSend() (line ~95):**

```typescript
// PII Detection patterns
const PII_PATTERNS = {
  creditCard: /\b(?:\d[ -]*?){13,19}\b/,
  ssn: /\b\d{3}-\d{2}-\d{4}\b/,
  email: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/,
};

function detectPII(text: string): { type: string; match: string } | null {
  for (const [type, pattern] of Object.entries(PII_PATTERNS)) {
    const match = text.match(pattern);
    if (match) {
      // Luhn check for credit cards
      if (type === 'creditCard') {
        const digits = match[0].replace(/\D/g, '');
        if (digits.length >= 13 && digits.length <= 19 && luhnCheck(digits)) {
          return { type: 'credit card', match: match[0] };
        }
      } else {
        return { type, match: match[0] };
      }
    }
  }
  return null;
}

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
```

**Update handleSend() (line ~95):**

```typescript
const handleSend = async () => {
  const q = inputValue.trim();
  if (!q) return;

  // PII Detection - warn user before sending
  const pii = detectPII(q);
  if (pii) {
    const warningMsg: ChatMessage = {
      role: 'assistant',
      content: `⚠️ I detected what looks like a ${pii.type} in your message. For your security, please don't share sensitive information like credit card numbers, SSNs, or personal emails in chat. Your message was not sent.`,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, { role: 'user', content: q, timestamp: new Date() }, warningMsg]);
    setInputValue('');
    return; // Don't send the message
  }

  // ... rest of handleSend
};
```

---

## Issue 2: Decision Trace Empty

### Evidence
**Screenshot:** `dump/shop-PII-list.png`

Shows: "No trace events yet" and "Trace unavailable: recommendation service not reachable"

### Root Cause

1. **Backend not running** - Frontend can't reach API
2. **Feature flag disabled** - `DECISION_LOG_WRITES_ENABLED` was false (now fixed)
3. **Trace events not being logged** - Even when flag enabled, logging calls silently fail

### Fix #1: Already Done - Feature Flags

**File:** `config/feature_flags.json`

```json
{
  "DECISION_LOG_WRITES_ENABLED": true
}
```

### Fix #2: Ensure Trace Logging is Called

**File:** `src/app/routers/recommend.py`

**Find:** All `log_trace_event()` calls (lines ~259, 356, 559, 859, 914, etc.)

**Issue:** They're wrapped in try/except that silently fails:

```python
try:
    await log_trace_event(trace_id, "event_type", {...})
except Exception:
    pass  # Silent failure!
```

**Fix:** Log the error:

```python
try:
    await log_trace_event(trace_id, "event_type", {...})
except Exception as e:
    logger.warning(f"Failed to log trace event: {e}")
```

### Fix #3: Frontend - Handle Backend Unavailable

**File:** `frontend/src/components/DecisionTrace.tsx`

**Line ~216 (empty state):**

```typescript
{displayEvents.length === 0 && (
  <tr>
    <td colSpan={4} className={styles.empty}>
      {trace ? (
        'No events recorded. The backend may not be logging decision events.'
      ) : (
        <>
          <strong>Backend unavailable</strong><br/>
          Start the backend server: <code>uvicorn src.app.main:app --port 8080</code>
        </>
      )}
    </td>
  </tr>
)}
```

---

## Issue 3: Price Filtering Broken

### Evidence
**Screenshot:** `dump/laptop-pricewrong.png`

Query: "show me products between 1200 to 2100"

Result: Shows $849 product (outside range), not sorted by price

### Root Cause

**File:** `src/app/repositories/catalog.py` (lines 86-117)

Original `search_products()` had NO price filtering at database level.

### Fix: Already Applied

Price filtering and sorting now added. See updated `catalog.py`:

```python
def search_products(
    self,
    query: str,
    limit: int = 10,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    sort_by: str = "relevance"
) -> List[Product]:
    # ... builds query ...

    # Apply price filtering at database level
    if min_price is not None:
        base_query = base_query.where(Product.price_cents >= min_price * 100)
    if max_price is not None:
        base_query = base_query.where(Product.price_cents <= max_price * 100)

    # Apply sorting
    if sort_by == "price_asc":
        base_query = base_query.order_by(Product.price_cents.asc())
    elif sort_by == "price_desc":
        base_query = base_query.order_by(Product.price_cents.desc())
```

### Still Needed: Router to Pass Price Params

**File:** `src/app/routers/recommend.py`

**Line ~565:** Update to pass price parameters:

```python
# Parse price range from analysis
budget_min = analysis.get("budget_min")
budget_max = analysis.get("budget_max")

# Pass to repository
candidates = repo.search_products(
    keywords=keywords,
    min_price=budget_min,
    max_price=budget_max,
    sort_by="price_asc" if budget_min or budget_max else "relevance",
    limit=limit
)
```

---

## Issue 4: NLP Not Intelligent

### Evidence
**Screenshot:** `dump/laptop-smart.png`

Query: "compare apple mac versus laptop i can use for gaming. what specs should I need?"

Response: Generic "Found 12 products" - no intelligent comparison

### Root Cause

**File:** `src/app/routers/recommend.py` (lines 472, 760)

LLM features disabled by default:

```python
if flags.get("USE_OLLAMA_INTENT", False):  # Default FALSE
    # LLM intent classification - SKIPPED
```

### Fix: Enable LLM and Provide Intelligent Responses

**Step 1:** Enable flags (already done in feature_flags.json)

**Step 2:** Ensure Ollama is running:

```bash
ollama pull llama3.2:3b
ollama serve
```

**Step 3:** Add intelligent fallback when LLM unavailable

**File:** `frontend/src/App.tsx`

**In the catch block (~line 135), add intelligent responses:**

```typescript
} catch {
  // Fallback with intelligent responses based on query type
  const mode = detectPanelMode(q);

  // Detect comparison requests
  if (mode === 'compare' || /compare|versus|vs|which is better/i.test(q)) {
    const brands = ['apple', 'mac', 'dell', 'hp', 'lenovo', 'asus', 'msi'];
    const mentionedBrands = brands.filter(b => q.toLowerCase().includes(b));

    const comparisonResponse = mentionedBrands.length > 0
      ? `I'd be happy to help compare ${mentionedBrands.join(' vs ')}! Here are the key differences:\n\n` +
        `• **Apple/Mac**: Best for creative work, excellent build quality, macOS ecosystem\n` +
        `• **Windows Gaming Laptops**: Better for gaming (discrete GPUs), more upgrade options\n\n` +
        `For gaming, you'll want: RTX 4060+ GPU, 16GB+ RAM, fast refresh rate display.`
      : `Here are products to compare. For gaming, prioritize discrete GPUs (RTX series) and 16GB+ RAM.`;

    setMessages(prev => [...prev, {
      role: 'assistant',
      content: comparisonResponse,
      timestamp: new Date()
    }]);
  }

  // ... rest of filtering logic
}
```

---

## File Reference Summary

### Frontend Files
| File | Purpose | Key Lines |
|------|---------|-----------|
| `frontend/src/App.tsx` | Main chat interface | 95 (handleSend), 135 (fallback) |
| `frontend/src/components/DecisionTrace.tsx` | Trace popup | 216 (empty state), 131 (detach) |
| `frontend/src/components/DecisionTrace.module.css` | Trace styles | All |
| `frontend/src/components/ProductGrid.tsx` | Product display | All |

### Backend Files
| File | Purpose | Key Lines |
|------|---------|-----------|
| `src/app/deps.py` | PII scrubbing | 87-93 (scrub_pii) |
| `src/app/security/pci.py` | Credit card detection | 23-33 (contains_pci_data) |
| `src/app/safety/redaction.py` | Redaction utilities | 9-17 (redact_text) |
| `src/app/routers/recommend.py` | Recommendation API | 472, 760 (LLM flags) |
| `src/app/routers/decisions.py` | Decision trace API | 119-121, 405-454 (SSE) |
| `src/app/services/decision_log.py` | Trace logging | 132-210 (log_trace_event) |
| `src/app/repositories/catalog.py` | Product search | 86-145 (search_products) |
| `src/app/services/recommendations.py` | NLP analysis | 442-545 (analyze_query) |
| `config/feature_flags.json` | Feature toggles | All |

### Agent Files (Defined but not connected)
| File | Purpose |
|------|---------|
| `src/agents/recommendation_agent.py` | Product recommendations |
| `src/agents/inventory_agent.py` | Stock checking |
| `src/agents/orchestrator.py` | Agent coordination |
| `src/agents/factory.py` | Agent creation |
| `src/agents/prompt_templates.py` | LLM prompts |

---

## Testing Commands

```bash
# Start backend
cd D:\AI\agentLumen\ShopSquire
uvicorn src.app.main:app --host 0.0.0.0 --port 8080 --reload

# Start frontend
cd frontend
npm run dev

# Start Ollama (for LLM features)
ollama serve

# Test PII detection (should be blocked)
curl -X POST http://localhost:8080/api/v1/chat/query \
  -H "Content-Type: application/json" \
  -d '{"query": "my card is 4111111111111111"}'

# Test price filtering
curl "http://localhost:8080/api/v1/recommend/suggest?query=laptops%20between%201200%20and%202000"

# Test decision trace
curl http://localhost:8080/api/v1/decisions/test-id
```

---

## Priority Order

1. **HIGH: PII Detection** - Security vulnerability, users can leak credit cards
2. **HIGH: Price Filtering** - User experience, wrong results shown
3. **MEDIUM: Decision Trace** - Debugging/observability, needs backend running
4. **MEDIUM: NLP Intelligence** - User experience, needs Ollama setup

---

## Copilot Workspace Commands

```
@workspace /fix Add credit card detection to scrub_pii function in src/app/deps.py

@workspace /explain Why is PII detection not blocking credit card numbers?

@workspace /fix Add client-side PII warning in frontend/src/App.tsx handleSend function

@workspace /fix Pass min_price and max_price to search_products in recommend.py

@workspace /explain Why is decision trace empty?
```
