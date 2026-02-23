# ShopSquire Frontend Wiring and Integration Guide

**Generated:** 2026-01-26
**Purpose:** Complete documentation of frontend-to-backend wiring, button functionality, agent integration, and testing procedures.

---

## 1. Architecture Overview

```
+------------------+     +------------------+     +------------------+
|   React Frontend |<--->|   FastAPI Backend|<--->|   PostgreSQL DB  |
|   (Storefront)   |     |   (Orchestrator) |     |   (TimescaleDB)  |
+------------------+     +------------------+     +------------------+
        |                        |                        |
        v                        v                        v
+------------------+     +------------------+     +------------------+
|   Custom CSS     |     |   Ollama LLM     |     | Bitemporal Logs  |
|   (styles.css)   |     |   (llama3.1:8b)  |     | decision_logs    |
+------------------+     +------------------+     +------------------+
```

---

## 2. API Endpoint Wiring

### 2.1 Product Recommendations
| Frontend Action | API Endpoint | Method | Request | Response |
|-----------------|--------------|--------|---------|----------|
| Chat query | `/api/v1/recommend/suggest` | GET | `?uid=&query=` | `{results, trace_id, decision_id, agent_chain}` |
| Product detail | `/api/v1/products/{sku}` | GET | - | `{sku, name, price_cents, specs, stock}` |
| Catalog load | `/ui/products.json` | GET | - | `[{sku, name, price_cents, features}]` |

### 2.2 Cart Operations
| Frontend Action | API Endpoint | Method | Request | Response |
|-----------------|--------------|--------|---------|----------|
| Get cart | `/api/v1/cart` | GET | `?uid=` | `{cart_id, items, subtotal_cents}` |
| Add item | `/api/v1/cart/items` | POST | `{uid, sku, quantity}` | `{cart_id, items}` |
| Remove item | `/api/v1/cart/items/{sku}` | DELETE | `?uid=` | `{cart_id, items}` |
| Clear cart | `/api/v1/cart/clear` | POST | `?uid=` | `{status}` |

### 2.3 Orders and Checkout
| Frontend Action | API Endpoint | Method | Request | Response |
|-----------------|--------------|--------|---------|----------|
| Create order | `/api/v1/orders/create` | POST | `{uid, items}` | `{order_id, status, total_cents}` |
| Order status | `/api/v1/orders/{order_id}` | GET | - | `{order_id, status, items}` |
| Order history | `/api/v1/orders/history` | GET | `?uid=&page=&limit=` | `{orders, total, page}` |

### 2.4 CV Complaint Submission
| Frontend Action | API Endpoint | Method | Request | Response |
|-----------------|--------------|--------|---------|----------|
| Submit complaint | `/api/v1/support/complaints/submit` | POST | `FormData(order_id, issue_type, description, images[])` | `{case_id, decision, cv_analysis}` |
| Poll status | `/api/v1/support/complaints/{case_id}/status` | GET | - | `{case_id, decision, cv_analysis, fraud_signals}` |

### 2.5 Decision Trace
| Frontend Action | API Endpoint | Method | Request | Response |
|-----------------|--------------|--------|---------|----------|
| Fetch trace | `/api/v1/decisions/{trace_id}` | GET | - | `{decision_id, policy_version, agent_chain, security, playbook}` |

### 2.6 Human Escalation and Approvals
| Frontend Action | API Endpoint | Method | Request | Response |
|-----------------|--------------|--------|---------|----------|
| Approve | `/api/v1/approvals/{approval_id}/approve` | POST | - | `{approved, decision_id}` |
| Reject | `/api/v1/approvals/{approval_id}/reject` | POST | - | `{approved, decision_id}` |
| Escalate | `/api/v1/support/escalate` | POST | `{case_id, reason}` | `{ticket_id, ticket_url}` |

---

## 3. Button Functionality Matrix

### 3.1 Header Buttons
| Button | Location | Action | State Changes |
|--------|----------|--------|---------------|
| Menu (hamburger) | Header left | Opens mobile sidebar | `mobileMenuOpen: true` |
| Search | Header center | Focus search input | N/A |
| Cart icon | Header right | Opens cart panel | `rightPanel: {type: 'cart'}` |
| Bell icon | Header right | Opens notifications | Future: notification panel |
| Gear icon | Header right | Opens decision trace | `devTraceOpen: true` |
| Demo Trace | Header right | Loads demo trace | `lastTrace: demoTrace` |

### 3.2 Chat Overlay Buttons
| Button | Location | Action | State Changes |
|--------|----------|--------|---------------|
| Gear | Chat header | Opens trace panel | `devTraceOpen: true` |
| Close | Chat header | Closes overlay | `chatOpen: false` |
| Camera | Input area | Opens file picker | `fileInputRef.click()` |
| Mic | Input area | Voice input (future) | N/A |
| Send | Input area | Sends message | Triggers `handleSendMessage()` |

### 3.3 Right Panel Buttons
| Button | Location | Action | State Changes |
|--------|----------|--------|---------------|
| Grid view | Panel header | Switch to grid | `viewMode: 'grid'` |
| List view | Panel header | Switch to list | `viewMode: 'list'` |
| Compare view | Panel header | Switch to compare | `viewMode: 'compare'` |
| Close | Panel header | Close panel | `rightPanel: {type: null}` |
| Add to Cart | Product card | Adds item | Calls `handleAddToCart()` |
| Details | Product card | Shows detail | Calls `handleViewDetail()` |
| Checkout | Cart panel | Creates order | Calls `handleCheckout()` |
| Approve/Reject | Approval panel | Handles approval | Calls `handleApprovalAction()` |
| Escalate | CV panel | Escalates to human | Opens approval panel |

---

## 4. Agent Chain and Bitemporal Decision Trace

### 4.1 Agent Orchestration Flow
```
User Query
    |
    v
+-------------------+
| Security Observer | <- Checks OWASP LLM Top 10, MITRE ATT&CK
| (28ms)            |    Outputs: risk_score, security signals
+-------------------+
    |
    v
+-------------------+
| NLP Intent Agent  | <- Parses query, extracts constraints
| (120ms)           |    Outputs: intent, constraints, view_mode
+-------------------+
    |
    v
+-------------------+
| Retrieval Agent   | <- Fetches products, applies filters
| (132ms)           |    Outputs: candidate products, scores
+-------------------+
    |
    v
+-------------------+
| Policy Agent      | <- Evaluates trust tier, discount rules
| (45ms)            |    Outputs: policy_gates, approval_needed
+-------------------+
    |
    v
+-------------------+
| Response Agent    | <- Formats response, selects view mode
| (24ms)            |    Outputs: results, explanation
+-------------------+
    |
    v
Decision Logged (Bitemporal)
```

### 4.2 Bitemporal Decision Logging

Each decision is logged with:
- `valid_from` / `valid_to`: Business time (when the decision applies)
- `system_from` / `system_to`: System time (when the record was created/modified)
- `decision_id`: Unique identifier
- `trace_id`: Links to full trace
- `agent_chain`: Array of agent names, confidence scores, durations
- `policy_version`: Which policy was applied
- `execution_status`: pending, executed, rejected

**Schema:**
```sql
CREATE TABLE decision_logs (
    id UUID PRIMARY KEY,
    decision_id TEXT NOT NULL,
    trace_id TEXT,
    agent_name TEXT,
    policy_version TEXT,
    execution_status TEXT,
    risk_score FLOAT,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ DEFAULT '9999-12-31',
    system_from TIMESTAMPTZ DEFAULT NOW(),
    system_to TIMESTAMPTZ DEFAULT '9999-12-31',
    payload JSONB
);
```

### 4.3 Trace Panel Display

The gear icon opens `DevTracePanel` which shows:

| Section | Data Source | Fields Displayed |
|---------|-------------|------------------|
| Summary | `lastTrace` | decision_id, policy_version, trace_id, risk_score |
| Tiered Model | `lastTrace.llm_model` | model name, tier, complexity signals |
| Intent | `lastTrace.intent_analysis` | parsed intent, constraints |
| Agent Chain | `lastTrace.agent_chain` | agent name, confidence, duration_ms |
| Evidence | `lastTrace.retrieved_context` | RAG context, playbook |
| Policy Gates | `lastTrace.policy_gates` | applied rules, pass/fail |
| Security | `lastTrace.security` | MITRE, OWASP, DREAD, CVSS |
| Playbook | `lastTrace.playbook` | playbook ID, severity, actions |

---

## 5. Tiered Ollama LLM Integration

### 5.1 Model Tiers

| Tier | Model | Use Case | Complexity Threshold |
|------|-------|----------|---------------------|
| Fast | llama3.2:1b | Simple queries, FAQ | complexity < 0.3 |
| Standard | llama3.1:8b | Product recommendations | 0.3 <= complexity < 0.7 |
| Advanced | llama3.1:70b | Complex comparisons, analysis | complexity >= 0.7 |

### 5.2 Complexity Signals

The backend calculates complexity based on:
- Query length (> 50 chars adds 0.1)
- Compare keywords (adds 0.2)
- Technical specs requested (adds 0.15)
- Price range queries (adds 0.1)
- Multi-product queries (adds 0.15)

### 5.3 Testing Tiered LLM

**Test Script:**
```bash
# Test Fast tier (simple query)
curl "http://localhost:8080/api/v1/recommend/suggest?uid=test&query=laptops" \
  -H "x-api-key: local-developer-key"
# Expect: model_tier: "fast"

# Test Standard tier (price range)
curl "http://localhost:8080/api/v1/recommend/suggest?uid=test&query=gaming+laptops+under+2000" \
  -H "x-api-key: local-developer-key"
# Expect: model_tier: "standard"

# Test Advanced tier (complex comparison)
curl "http://localhost:8080/api/v1/recommend/suggest?uid=test&query=compare+ThinkPad+X1+vs+Dell+XPS+15+battery+life+performance+thermals" \
  -H "x-api-key: local-developer-key"
# Expect: model_tier: "advanced"
```

**Frontend Verification:**
1. Open chat overlay
2. Send query
3. Click gear icon
4. Check "Tiered Model" section for:
   - `Model`: which Ollama model was used
   - `Tier`: fast/standard/advanced
   - `Complexity`: 0.0-1.0 score
   - `Signals`: which factors contributed

### 5.4 Backend Configuration

```python
# src/app/services/llm_provider.py
TIERED_MODELS = {
    "fast": "llama3.2:1b",
    "standard": "llama3.1:8b",
    "advanced": "llama3.1:70b"
}

def select_model(complexity: float) -> str:
    if complexity < 0.3:
        return "fast"
    elif complexity < 0.7:
        return "standard"
    else:
        return "advanced"
```

---

## 6. Right Panel State Changes

### 6.1 State Machine

```
                    +----------+
                    | PRODUCTS |<---- Default on query
                    +----------+
                         |
        +----------------+----------------+
        |                |                |
        v                v                v
   +---------+     +---------+     +---------+
   |  GRID   |     |  LIST   |     | COMPARE |
   +---------+     +---------+     +---------+
        |                |                |
        +----------------+----------------+
                         |
        +----------------+----------------+----------------+
        |                |                |                |
        v                v                v                v
   +---------+     +---------+     +---------+     +---------+
   |  CART   |     |   CV    |     | APPROVAL|     | CHECKOUT|
   +---------+     +---------+     +---------+     +---------+
        |                |                |                |
        v                v                v                v
    [Checkout]    [Escalate]      [Approve]      [Confirm]
                                  [Reject]
```

### 6.2 Trigger Conditions

| Panel State | Trigger | Backend Response Field |
|-------------|---------|------------------------|
| `products` | Query with product intent | `results.length > 0` |
| `cart` | Click cart icon or "Add to Cart" | `cartState.items` |
| `cv` | Upload images with complaint | `case_id` present |
| `approval` | Security block or escalation | `approval_id` present |
| `checkout` | Complete order creation | `order_id` present |
| `product_detail` | Click "Details" on product | Product object |

### 6.3 CV Complaint Panel Behavior

When images are uploaded:
1. Panel switches to `type: 'cv'`
2. Horizontal scrollable image gallery at top
3. Status card shows:
   - Case ID
   - Processing state
   - Agent verdict (when complete)
   - Confidence score
   - Severity level
   - Policy applied
4. Polling continues until terminal state
5. "Escalate to Human" button available

### 6.4 Security Event Detection

When security threat detected:
1. Backend returns `status: 'blocked'` or `status: 'degraded'`
2. Chat shows warning message with human handoff option
3. Right panel switches to `type: 'approval'`
4. Shows:
   - Approval ID
   - Reason (security_review, fraud_detected, etc.)
   - Ticket link if created
5. User can click "Request human review"

---

## 7. Cart to Checkout Flow (PCI-DSS Compliant)

### 7.1 Flow Stages

```
CART --> SHIPPING --> PAYMENT --> CONFIRMATION
  |          |            |            |
  |          |            |            +-> Order created
  |          |            +-> Stripe handles PCI data
  |          +-> Address collected (server-side)
  +-> Items reviewed
```

### 7.2 PCI-DSS Compliance

**Critical Rule:** Agents NEVER have access to:
- Card numbers
- CVV/CVC
- Full PAN
- Billing address for payment

**Implementation:**
1. Use Stripe Elements (iframe) for card input
2. Card data goes directly to Stripe, never touches our server
3. Backend only receives Stripe token/payment intent ID
4. Agent logs show `[REDACTED]` for any payment fields

```javascript
// Payment component (Stripe Elements)
<CardElement
  options={{
    hidePostalCode: true,
    style: { base: { fontSize: '16px' } }
  }}
/>

// On submit - card data goes to Stripe directly
const { error, paymentMethod } = await stripe.createPaymentMethod({
  type: 'card',
  card: elements.getElement(CardElement),
});

// Only token sent to backend
await fetch('/api/v1/payments/confirm', {
  body: JSON.stringify({ payment_method_id: paymentMethod.id, order_id })
});
```

### 7.3 Checkout API Flow

```
1. POST /api/v1/orders/create
   - Creates order with items
   - Returns order_id, total_cents

2. POST /api/v1/payments/intent
   - Creates Stripe PaymentIntent
   - Returns client_secret (for frontend Stripe)

3. Frontend: stripe.confirmCardPayment(client_secret)
   - User enters card in Stripe iframe
   - Stripe processes payment

4. POST /api/v1/payments/confirm
   - Receives payment_method_id only
   - Updates order status
   - Logs decision (no PII)
```

---

## 8. Human Escalation Flow

### 8.1 Escalation Triggers

| Trigger | Condition | Action |
|---------|-----------|--------|
| Security block | `risk_score > 70` | Auto-escalate |
| Fraud detection | CV analysis flags fraud | Escalate to fraud team |
| PII detected | Agent sees card/SSN | Immediate block + escalate |
| User request | Clicks "Talk to human" | Create support ticket |
| Policy override | Discount > threshold | Queue for approval |

### 8.2 Escalation UI

In chat panel (left side):
```
Assistant: I cannot process this request automatically.
           Would you like to speak with a human agent?
           [Request Human Review]
```

When clicked:
1. Creates approval record
2. Optionally creates external ticket (Zendesk, etc.)
3. Right panel shows approval status
4. Chat shows confirmation with ticket link

### 8.3 Backend Escalation Endpoint

```python
# POST /api/v1/support/escalate
{
    "case_id": "CV-12345",      # Optional
    "order_id": "ORD-67890",    # Optional
    "reason": "customer_request",
    "context": "User requested human review after security check"
}

# Response
{
    "ticket_id": "TKT-001",
    "ticket_url": "https://support.example.com/tickets/TKT-001",
    "approval_id": "APR-456",
    "estimated_response": "2 hours"
}
```

---

## 9. Testing Checklist

### 9.1 Product Recommendations
- [ ] Simple query returns products
- [ ] Price range query shows grid view
- [ ] Compare query shows comparison table
- [ ] Detail query shows list view
- [ ] Backend override of view_mode works
- [ ] Trace shows agent chain

### 9.2 Cart Operations
- [ ] Add to cart updates cart state
- [ ] Cart icon shows item count
- [ ] Remove item works
- [ ] Quantity update works
- [ ] Checkout button enabled with items

### 9.3 CV Complaints
- [ ] Image upload accepts jpg/png
- [ ] File size limit enforced (10MB)
- [ ] Panel shows uploaded images
- [ ] Status polling works
- [ ] Verdict displays correctly
- [ ] Escalate button works

### 9.4 Decision Trace
- [ ] Gear icon appears after query
- [ ] Trace panel shows all sections
- [ ] Agent chain displays correctly
- [ ] Security signals shown
- [ ] Copy JSON works
- [ ] Live Ops link works

### 9.5 Checkout Flow
- [ ] Cart to shipping transition
- [ ] Address form validation
- [ ] Stripe Elements loads
- [ ] Payment processes (test mode)
- [ ] Confirmation displays order ID
- [ ] Cart clears after checkout

### 9.6 Security and Escalation
- [ ] Blocked response shows warning
- [ ] Human handoff button works
- [ ] Approval panel shows correctly
- [ ] Approve/Reject buttons work
- [ ] Ticket link opens correctly

---

## 10. Environment Variables

```bash
# Frontend (.env)
VITE_API_BASE=http://localhost:8080/api/v1
VITE_API_KEY=local-developer-key
VITE_STRIPE_PUBLISHABLE_KEY=pk_test_xxx

# Backend (.env)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL_FAST=llama3.2:1b
OLLAMA_MODEL_STANDARD=llama3.1:8b
OLLAMA_MODEL_ADVANCED=llama3.1:70b
STRIPE_SECRET_KEY=sk_test_xxx
DATABASE_URL=postgresql://...
```

---

## 11. File Structure

```
src/frontend/storefront-react/
  src/
    App.jsx              # Main component (edit this)
    main.jsx             # Entry point
    styles.css           # Custom styles and design tokens
  index.html
  package.json
  vite.config.js

Key Components in App.jsx:
- ShopSquireApp        # Main container
- ChatOverlay          # Draggable chat modal
- RightPanel           # Products/Cart/CV/Approval panel
- DevTracePanel        # Decision trace modal
- ProductGrid          # Grid/List/Compare views
- MobileMenu           # Mobile sidebar
- OpsOverlay           # Admin ops iframe
```

---

## 12. Quick Reference: State Variables

| State | Type | Purpose |
|-------|------|---------|
| `chatOpen` | boolean | Chat overlay visibility |
| `rightPanel` | `{type, data, meta}` | Right panel content |
| `viewMode` | `'grid' | 'list' | 'compare'` | Product display mode |
| `messages` | array | Chat message history |
| `cartState` | object | Cart items and totals |
| `lastTrace` | object | Most recent decision trace |
| `devTraceOpen` | boolean | Trace panel visibility |
| `cvStatus` | object | CV complaint status |
| `pendingUploads` | array | Files waiting to upload |
| `isLoading` | boolean | API request in progress |

---

*This document serves as the single source of truth for frontend-backend integration in ShopSquire.*
