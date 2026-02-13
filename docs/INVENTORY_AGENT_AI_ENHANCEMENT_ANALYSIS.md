# ShopSquire Inventory Agent: AI/ML Enhancement Analysis

> **Document Purpose**: Strategic analysis for smarter inventory operations, supplier management, CV interaction defaults, autonomy progression, and infrastructure considerations.
> **Author Context**: This document demonstrates business process thinking, AI architecture awareness, and operational maturity.

---

## Table of Contents
1. [Current State Assessment](#current-state-assessment)
2. [AI/ML Techniques for Inventory Intelligence](#aiml-techniques-for-inventory-intelligence)
3. [50+ Customer Stock Interaction Rules](#50-customer-stock-interaction-rules)
4. [Stocktake and Quality Checking](#stocktake-and-quality-checking)
5. [Supplier Interaction and Dispute Management](#supplier-interaction-and-dispute-management)
6. [Email Security: BEC/DMARC Concerns](#email-security-becdmarc-concerns)
7. [Default CV Interaction Design](#default-cv-interaction-design)
8. [Neural Network Considerations](#neural-network-considerations)
9. [Path to Autonomy (1-5 Steps)](#path-to-autonomy-1-5-steps)
10. [Supplier Contract Facilitation](#supplier-contract-facilitation)
11. [Reducing GPU/LLM/API Token Reliance](#reducing-gpullmapi-token-reliance)
12. [IOPs and Object Storage Considerations](#iops-and-object-storage-considerations)
13. [Career Development: Operations, Business Process, AI Architecture](#career-development)
14. [TOGAF Considerations](#togaf-considerations)

---

## Current State Assessment

### What ShopSquire Inventory Agent Already Has

| Component | Current Implementation | Maturity |
|-----------|----------------------|----------|
| Stock Monitoring | SQL-based threshold alerts | Basic |
| Supplier Scoring | Weighted multi-factor (cost, lead time, on-time rate, reliability) | Good |
| EOQ Calculation | EWMA-based demand smoothing | Good |
| Reorder Execution | PO creation with approval workflow | Good |
| Stocktake Reconciliation | Variance detection with escalation | Basic |
| Decision Logging | Full audit trail with trace events | Excellent |
| Guardrails | Cost thresholds, ticket-based approvals | Good |

### Gaps to Address

1. **No predictive demand forecasting** (only reactive EWMA)
2. **No supplier quality scoring** from historical disputes
3. **No customer-facing stock communication rules**
4. **Limited CV integration** for goods receipt
5. **No email authentication in supplier communications**
6. **Manual escalation thresholds** (not learned)

---

## AI/ML Techniques for Inventory Intelligence

### Tier 1: Rule-Based + Statistical (No GPU Required)

These techniques work **without LLMs or deep learning**:

| Technique | Use Case | Implementation Complexity |
|-----------|----------|---------------------------|
| **Exponential Smoothing (Holt-Winters)** | Seasonal demand forecasting | Low - Pure Python |
| **Moving Average Crossover** | Trend detection for reorder timing | Low |
| **Z-Score Anomaly Detection** | Unusual demand spikes/drops | Low |
| **Bayesian Inference** | Supplier reliability updates | Medium |
| **Decision Trees (sklearn)** | Supplier selection rules | Low - CPU only |
| **Association Rules (Apriori)** | "Customers who bought X also need Y" | Low |
| **Markov Chains** | State transitions (in-stock -> low -> out) | Low |

```python
# Example: Holt-Winters without ML libraries
def holt_winters_forecast(history: list[float], alpha=0.3, beta=0.1, gamma=0.1, seasonal_periods=7):
    """Triple exponential smoothing for seasonal data."""
    n = len(history)
    if n < seasonal_periods * 2:
        return sum(history) / n  # Fallback to simple average

    # Initialize level, trend, seasonal components
    level = sum(history[:seasonal_periods]) / seasonal_periods
    trend = (sum(history[seasonal_periods:2*seasonal_periods]) - sum(history[:seasonal_periods])) / (seasonal_periods ** 2)
    seasonals = [history[i] - level for i in range(seasonal_periods)]

    for i in range(seasonal_periods, n):
        val = history[i]
        last_level = level
        season_idx = i % seasonal_periods
        level = alpha * (val - seasonals[season_idx]) + (1 - alpha) * (level + trend)
        trend = beta * (level - last_level) + (1 - beta) * trend
        seasonals[season_idx] = gamma * (val - level) + (1 - gamma) * seasonals[season_idx]

    return level + trend + seasonals[0]  # Next period forecast
```

### Tier 2: Lightweight ML (CPU-Friendly)

| Technique | Use Case | Library |
|-----------|----------|---------|
| **XGBoost/LightGBM** | Demand prediction, supplier risk | `xgboost` (CPU mode) |
| **Isolation Forest** | Anomaly detection in orders | `sklearn` |
| **K-Means Clustering** | Customer segmentation for stock priority | `sklearn` |
| **Random Forest** | Multi-factor supplier scoring | `sklearn` |
| **Linear Regression** | Lead time prediction | `sklearn` |

### Tier 3: Neural Networks (When Justified)

Use **only when Tier 1-2 fails** and you have sufficient data:

| Technique | Use Case | Justification |
|-----------|----------|---------------|
| **LSTM/GRU** | Time-series demand with complex patterns | > 2 years daily data |
| **Transformer (small)** | Multi-product demand correlation | > 10K SKUs, seasonal |
| **Embedding Models** | Product similarity for substitutions | > 50K products |

### Recommended Approach: Tiered Fallback

```
flowchart TD
    A[New Prediction Request] --> B{Has > 90 days history?}
    B -->|No| C[Simple Moving Average]
    B -->|Yes| D{Seasonal pattern detected?}
    D -->|No| E[Holt-Winters Double]
    D -->|Yes| F[Holt-Winters Triple]
    F --> G{Error > 20%?}
    G -->|No| H[Use Statistical Forecast]
    G -->|Yes| I{Has > 1 year data?}
    I -->|No| H
    I -->|Yes| J[Train XGBoost Model]
```

---

## 50+ Customer Stock Interaction Rules

These rules govern agent responses to customer stock inquiries. Designed for **deterministic execution without LLM calls**.

### Category 1: Stock Availability (Rules 1-10)

| # | Rule | Action | Escalate |
|---|------|--------|----------|
| 1 | Stock > 10 units | "In stock, ships within X days" | No |
| 2 | Stock 1-10 units | "Limited stock - X remaining" | No |
| 3 | Stock = 0, reorder in progress | "Temporarily out - back in ~X days" | No |
| 4 | Stock = 0, no reorder | "Currently unavailable" + suggest alternatives | No |
| 5 | Stock = 0, discontinued | "No longer available" + suggest replacement | No |
| 6 | Reserved stock for order | Reduce displayed available by reserved | No |
| 7 | Stock across multiple warehouses | Show nearest warehouse availability | No |
| 8 | Pre-order available | "Available for pre-order, ships X" | No |
| 9 | Backorder accepted | "Backorder available, lead time X days" | No |
| 10 | Stock discrepancy detected | Hold response, flag for verification | Yes |

### Category 2: Customer Context (Rules 11-20)

| # | Rule | Action | Escalate |
|---|------|--------|----------|
| 11 | VIP customer + low stock | Reserve 1 unit for 4 hours | No |
| 12 | Repeat customer + frequent purchases | Proactive "stock arriving" notification | No |
| 13 | B2B customer + bulk inquiry | Route to account manager workflow | Yes |
| 14 | Guest user + high-value item | Require email for stock alerts | No |
| 15 | Customer in high-fraud region + stock check | Log but don't restrict | No |
| 16 | Customer timezone = off-hours | Adjust "ships today" to next business day | No |
| 17 | Customer preferred warehouse set | Prioritize that warehouse stock | No |
| 18 | Customer has open return for same SKU | Flag potential abuse pattern | Yes |
| 19 | Customer checking same SKU > 5 times | Offer stock alert subscription | No |
| 20 | Customer segment = "price sensitive" | Include restock sale alert option | No |

### Category 3: Product Context (Rules 21-30)

| # | Rule | Action | Escalate |
|---|------|--------|----------|
| 21 | Perishable product + stock query | Show expiry-adjusted availability | No |
| 22 | Serial-tracked product | Confirm serial availability | No |
| 23 | Bundle product | Check all component availability | No |
| 24 | Made-to-order product | Show lead time, not "stock" | No |
| 25 | Drop-ship product | Query supplier API (cached 15 min) | No |
| 26 | Hazmat product + international shipping | Check destination restrictions | No |
| 27 | High-theft-risk product | Don't show exact stock counts | No |
| 28 | Product under recall | "Currently unavailable" + reason | Yes |
| 29 | Product with active promotion | Show promotion-adjusted stock allocation | No |
| 30 | Newly launched product | "Limited initial stock" messaging | No |

### Category 4: Timing and Urgency (Rules 31-40)

| # | Rule | Action | Escalate |
|---|------|--------|----------|
| 31 | Customer mentions "urgent" | Expedited shipping options | No |
| 32 | Stock query during flash sale | Rate-limit stock API calls | No |
| 33 | Stock < 3 + high demand velocity | "Selling fast - X left" | No |
| 34 | End of quarter + B2B | Highlight volume discount deadlines | No |
| 35 | Stock replenishment < 24 hours | "More arriving tomorrow" | No |
| 36 | Weekend stock query | Adjust ship dates for Monday dispatch | No |
| 37 | Holiday period | Extend lead times automatically | No |
| 38 | Last unit + multiple concurrent queries | First-come-first-serve queue | No |
| 39 | Stock arriving + customer waiting > 3 days | Proactive notification | No |
| 40 | Promotional period ending | "Last chance" messaging | No |

### Category 5: Alternative Suggestions (Rules 41-50)

| # | Rule | Action | Escalate |
|---|------|--------|----------|
| 41 | Out of stock + similar product in stock | Suggest alternative with comparison | No |
| 42 | Out of stock + higher model available | Upsell suggestion | No |
| 43 | Out of stock + lower model available | Downgrade suggestion with savings | No |
| 44 | Out of stock + competitor price match | Note price match policy | No |
| 45 | Out of stock + rental/lease option | Suggest temporary alternative | No |
| 46 | Out of stock + refurbished available | Suggest refurbished with warranty info | No |
| 47 | Color/size variant out + others available | Suggest available variants | No |
| 48 | Bundle component out + standalone available | Suggest standalone purchase | No |
| 49 | Accessory out + main product in stock | Proceed with main, backorder accessory | No |
| 50 | All variants out | Notify when any variant restocks | No |

### Category 6: Guardrails and Safety (Rules 51-60)

| # | Rule | Action | Escalate |
|---|------|--------|----------|
| 51 | Customer requests > max order quantity | Enforce limit with explanation | No |
| 52 | Stock query reveals pricing error | Hold, alert pricing team | Yes |
| 53 | Customer attempts to reserve entire stock | Limit to fair-use quantity | Yes |
| 54 | Unusual bulk inquiry pattern | Flag for review | Yes |
| 55 | Customer claims stock shown != received | Trigger reconciliation audit | Yes |
| 56 | Stock data > 1 hour stale | Show "verify at checkout" | No |
| 57 | API timeout on stock check | "Stock information temporarily unavailable" | No |
| 58 | Conflicting stock across systems | Use most conservative number | Yes |
| 59 | Customer in sanctioned region | Block order, log compliance | Yes |
| 60 | Product + customer combination = high fraud risk | Require verification | Yes |

---

## Stocktake and Quality Checking

### Enhanced Reconciliation Workflow

```
flowchart TD
    A[Stocktake Initiated] --> B[Count Physical Stock]
    B --> C{Barcode/RFID Scan?}
    C -->|Yes| D[Automated Count via Scanner]
    C -->|No| E[Manual Count Entry]
    D --> F[Compare to System Stock]
    E --> F
    F --> G{Variance > 5%?}
    G -->|No| H[Auto-Approve, Update System]
    G -->|Yes| I{Variance > 15%?}
    I -->|No| J[Flag for Supervisor Review]
    I -->|Yes| K[Escalate + Freeze SKU Sales]
    J --> L[Review Within 24h]
    K --> M[Investigate Immediately]
```

### Quality Check Integration

| Check Point | Method | Automation Level |
|-------------|--------|------------------|
| **Goods Receipt** | CV inspection for damage | Semi-auto (photo required) |
| **Warehouse Shelf** | Periodic CV scan for condition | Can automate with cameras |
| **Pick/Pack** | Weight verification | Fully automated |
| **Returns Intake** | CV + manual inspection | Semi-auto |
| **Cycle Count** | Random SKU selection | Fully automated selection |

### Quality Scoring Model

```python
class ProductQualityScore:
    """Compute a 0-100 quality score for received goods."""

    FACTORS = {
        'packaging_intact': 0.20,
        'correct_quantity': 0.25,
        'no_visible_damage': 0.25,
        'correct_product': 0.20,
        'documentation_complete': 0.10,
    }

    def calculate(self, inspection: dict) -> float:
        score = 0.0
        for factor, weight in self.FACTORS.items():
            if inspection.get(factor, False):
                score += weight * 100
        return round(score, 1)

    def action_from_score(self, score: float) -> str:
        if score >= 95:
            return "accept"
        elif score >= 80:
            return "accept_with_note"
        elif score >= 60:
            return "partial_accept"
        else:
            return "reject"
```

---

## Supplier Interaction and Dispute Management

### Supplier Dispute Categories

| Category | Trigger | Auto-Action | Human-Required |
|----------|---------|-------------|----------------|
| **Quality Defect** | CV damage detection > threshold | Create dispute ticket | Negotiate replacement |
| **Short Shipment** | Received < Ordered | Auto-generate claim | Large discrepancies |
| **Late Delivery** | Actual > Expected + buffer | Log, update reliability | SLA breach notices |
| **Wrong Product** | SKU mismatch | Reject shipment | RMA process |
| **Documentation Error** | Invoice != PO | Hold payment | Reconciliation |
| **Damaged in Transit** | Carrier damage evidence | File carrier claim | Multi-party disputes |

### Supplier Reliability Decay Model

```python
class SupplierReliabilityTracker:
    """Bayesian update of supplier reliability with time decay."""

    def __init__(self, prior_alpha=10, prior_beta=2, decay_rate=0.02):
        self.alpha = prior_alpha  # Successful deliveries
        self.beta = prior_beta    # Failed deliveries
        self.decay_rate = decay_rate  # Per-month decay

    def record_delivery(self, success: bool, quality_score: float = 1.0):
        """Update reliability based on delivery outcome."""
        if success:
            self.alpha += quality_score
        else:
            self.beta += 1

    def apply_time_decay(self, months_passed: int):
        """Decay old evidence toward prior."""
        decay = (1 - self.decay_rate) ** months_passed
        self.alpha = 10 + (self.alpha - 10) * decay
        self.beta = 2 + (self.beta - 2) * decay

    @property
    def reliability_score(self) -> float:
        """Expected reliability (mean of Beta distribution)."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def confidence(self) -> float:
        """Confidence based on sample size."""
        n = self.alpha + self.beta
        return min(1.0, n / 100)  # Full confidence at 100 deliveries
```

### Automated Dispute Workflow

```python
DISPUTE_RULES = [
    # (condition, action, escalate_to)
    ("quality_score < 60 and order_value < 1000", "auto_claim_credit", None),
    ("quality_score < 60 and order_value >= 1000", "create_dispute_ticket", "procurement"),
    ("late_days > 7 and supplier.reliability < 0.8", "initiate_supplier_review", "procurement"),
    ("late_days > 14", "escalate_sla_breach", "management"),
    ("short_shipment_pct > 10", "auto_reorder_shortage", None),
    ("wrong_product", "reject_and_rma", "warehouse"),
    ("repeat_issue_same_supplier > 3", "supplier_probation_review", "procurement"),
]
```

---

## Email Security: BEC/DMARC Concerns

### Current Implementation Analysis

Your `email_validation.py` has basic BEC detection. Here's how to enhance it:

### Enhanced BEC Detection Rules

```python
BEC_RULES = {
    # Financial urgency
    "urgent_payment": {
        "patterns": ["urgent wire", "immediate transfer", "pay today", "send funds now"],
        "risk_score": 0.8,
        "action": "hold_and_verify"
    },
    # Account change fraud
    "account_change": {
        "patterns": ["new bank details", "update payment", "changed account", "new wire instructions"],
        "risk_score": 0.9,
        "action": "require_phone_verification"
    },
    # Gift card scams
    "gift_cards": {
        "patterns": ["buy gift cards", "itunes cards", "amazon codes", "prepaid cards"],
        "risk_score": 0.95,
        "action": "block_and_alert"
    },
    # Impersonation
    "executive_impersonation": {
        "patterns": ["ceo", "cfo", "urgent request from", "don't tell anyone"],
        "risk_score": 0.7,
        "action": "verify_sender_identity"
    },
    # Supplier fraud
    "supplier_impersonation": {
        "patterns": ["invoice attached", "overdue payment", "account suspended"],
        "risk_score": 0.6,
        "action": "verify_against_supplier_db"
    },
}
```

### DMARC/DKIM/SPF Enforcement Matrix

| Auth Result | Action | Supplier Communications | Internal Communications |
|-------------|--------|-------------------------|------------------------|
| All Pass | Accept | Process normally | Process normally |
| DMARC Fail Only | Quarantine | Manual review required | Manual review required |
| DKIM Fail | Quarantine | Verify sender via alternate channel | Block |
| SPF Fail | Quarantine | Log + proceed with caution | Manual review |
| All Fail | Reject | Auto-reject + alert | Block completely |

### Supplier Email Verification Workflow

```
flowchart TD
    A[Supplier Email Received] --> B{DMARC Pass?}
    B -->|Yes| C{DKIM Pass?}
    B -->|No| D[Quarantine + Alert]
    C -->|Yes| E{SPF Pass?}
    C -->|No| D
    E -->|Yes| F{Known Supplier Domain?}
    E -->|No| D
    F -->|Yes| G{Content BEC Check}
    F -->|No| H[Flag Unknown Sender]
    G -->|Clean| I[Process Communication]
    G -->|Suspicious| J[Require Phone Verification]
    D --> K[Manual Security Review]
    H --> K
```

### Automated Safe Sender Verification

```python
class SupplierEmailVerifier:
    """Verify supplier emails against known-good patterns."""

    def __init__(self, supplier_db):
        self.supplier_db = supplier_db
        self.verified_domains = set()
        self.verified_senders = set()

    def verify(self, email: dict) -> dict:
        from_addr = email.get("from", "")
        domain = from_addr.split("@")[-1].lower() if "@" in from_addr else ""

        checks = {
            "domain_registered": domain in self.verified_domains,
            "sender_known": from_addr.lower() in self.verified_senders,
            "reply_to_matches": email.get("reply_to", from_addr) == from_addr,
            "no_lookalike": not self._is_lookalike(domain),
            "dmarc_pass": email.get("auth", {}).get("dmarc_pass", False),
        }

        risk_score = sum(0.2 for v in checks.values() if not v)

        return {
            "checks": checks,
            "risk_score": risk_score,
            "action": "process" if risk_score < 0.4 else "verify" if risk_score < 0.6 else "block"
        }

    def _is_lookalike(self, domain: str) -> bool:
        """Check for typosquatting patterns."""
        import re
        # Common substitutions: rn->m, 0->o, l->1, vv->w
        sus_patterns = [
            r'(rn)(?=[a-z])',  # rn looks like m
            r'[0o]',           # 0/o confusion
            r'[1l]',           # 1/l confusion
            r'vv',             # vv looks like w
        ]
        return any(re.search(p, domain) for p in sus_patterns)
```

---

## Default CV Interaction Design

### Philosophy: Sensible Defaults, Client Extensible

Your positioning as a "modular agentic company" is correct. The default CV should:

1. **Work out-of-the-box** with common retail scenarios
2. **Be conservative** (false positives over false negatives)
3. **Provide clear extension points** for client customization
4. **Not require GPU** for basic operations

### Default CV Capabilities

| Capability | Default Behavior | Client Extension Point |
|------------|------------------|------------------------|
| **Damage Detection** | Binary: damaged/not-damaged | Custom damage taxonomy |
| **Label/OCR** | Extract serial numbers, barcodes | Custom label formats |
| **Product Identification** | Basic category (box, device, accessory) | Product-specific models |
| **Packaging Assessment** | Intact/tampered/damaged | Custom packaging criteria |
| **Document Verification** | Invoice presence detection | Custom document types |

### Tiered CV Architecture

```
Level 0: Hash-based duplicate detection (no ML)
    ↓ (if new image)
Level 1: Rule-based checks (file size, dimensions, format)
    ↓ (if passes)
Level 2: Statistical anomaly detection (histogram analysis)
    ↓ (if needed)
Level 3: Pre-trained lightweight model (MobileNet, ~4MB)
    ↓ (if high-value item)
Level 4: Full vision model (YOLO/LLaVA via API or local)
    ↓ (if dispute or audit)
Level 5: Client-specific fine-tuned model
```

### Recommended Default Models

| Use Case | Model | Size | Deployment |
|----------|-------|------|------------|
| **Basic Classification** | MobileNetV3-Small | 4MB | Edge/CPU |
| **Object Detection** | YOLOv8-Nano | 6MB | Edge/CPU |
| **OCR** | EasyOCR (CPU mode) | 20MB | Server |
| **Scene Understanding** | LLaVA-7B (quantized) | 4GB | API or GPU |

### Default CV Response Schema

```python
@dataclass
class CVInspectionResult:
    """Standard response from default CV inspection."""

    image_hash: str
    timestamp: str

    # Basic checks (no ML)
    file_valid: bool
    dimensions_ok: bool
    not_duplicate: bool

    # Statistical checks
    histogram_normal: bool
    blur_score: float  # 0-1, lower = more blur

    # ML-based (when available)
    damage_detected: bool
    damage_confidence: float
    damage_type: str | None  # "screen", "body", "packaging"

    # OCR results
    text_found: list[str]
    serial_numbers: list[str]
    barcodes: list[str]

    # Decision
    overall_assessment: str  # "pass", "review", "reject"
    confidence: float
    requires_human_review: bool

    # Extension hook
    custom_fields: dict  # For client-specific data
```

---

## Neural Network Considerations

### Why NOT to Over-Specialize

| Argument | Business Impact |
|----------|-----------------|
| **Training data requirements** | Clients need 1000s of labeled images per category |
| **Maintenance burden** | Model drift requires ongoing retraining |
| **Deployment complexity** | GPU infrastructure or API costs |
| **Regulatory risk** | Explainability requirements for automated decisions |
| **Client lock-in** | Custom models create switching costs |

### Recommended Network Types by Use Case

| Use Case | Network Type | Why This One |
|----------|--------------|--------------|
| **Damage Classification** | CNN (ResNet-18/50) | Well-understood, interpretable, transfer learning works |
| **Time-Series Forecasting** | TCN or small Transformer | Better than LSTM for long sequences, parallelizable |
| **Text Classification** | DistilBERT or TinyBERT | 90% of BERT performance at 40% size |
| **Product Matching** | Siamese Network | Good for few-shot learning |
| **Anomaly Detection** | Autoencoder | Unsupervised, works with limited data |

### The "No GPU" Default Path

```python
class AdaptiveInference:
    """Select inference path based on available resources."""

    def __init__(self):
        self.gpu_available = self._check_gpu()
        self.api_key_available = bool(os.getenv("VISION_API_KEY"))

    def select_path(self, task: str, urgency: str) -> str:
        if task == "damage_detection":
            if urgency == "realtime" and self.gpu_available:
                return "local_gpu"
            elif self.api_key_available:
                return "cloud_api"
            else:
                return "cpu_lightweight"

        elif task == "demand_forecast":
            # Statistical methods are always CPU-friendly
            return "statistical_cpu"

        elif task == "product_similarity":
            if self.api_key_available:
                return "embedding_api"
            else:
                return "tfidf_cpu"  # CPU-friendly alternative

        return "rule_based"  # Ultimate fallback

    def _check_gpu(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
```

---

## Path to Autonomy (1-5 Steps)

### Current State: Level 1-2 (Rule-Based with Human Approval)

### Target: Level 3-4 (Autonomous with Exception Handling)

### Step 1: Expand Rule Coverage (Current -> 6 months)

**Goal**: Handle 80% of scenarios without any ML.

| Enhancement | Impact | Guardrail |
|-------------|--------|-----------|
| 50+ stock rules implemented | Deterministic responses | All rules auditable |
| Supplier scoring automated | Consistent selection | Human override always available |
| Stocktake variance auto-categorization | Faster resolution | Large variances escalate |

**Metric**: % of decisions requiring no human input

### Step 2: Confidence-Based Escalation (6-12 months)

**Goal**: Learn when to escalate.

```python
class ConfidenceRouter:
    """Route decisions based on model confidence."""

    def __init__(self, thresholds: dict):
        self.thresholds = thresholds  # {"auto_approve": 0.95, "human_review": 0.7}

    def route(self, decision: dict) -> str:
        confidence = decision.get("confidence", 0)

        if confidence >= self.thresholds["auto_approve"]:
            return "auto_execute"
        elif confidence >= self.thresholds["human_review"]:
            return "human_review"
        else:
            return "human_decision"

    def learn_thresholds(self, historical_decisions: list):
        """Adjust thresholds based on human override patterns."""
        overrides = [d for d in historical_decisions if d.get("human_override")]
        if not overrides:
            return

        # Find confidence level where humans start overriding
        confidences = [d["confidence"] for d in overrides]
        self.thresholds["human_review"] = max(self.thresholds["human_review"],
                                               percentile(confidences, 10))
```

**Guardrails**:
- Maximum auto-approval value: $5,000 (configurable)
- New suppliers always require human approval for first 3 orders
- Any decision can be audited within 24 hours

### Step 3: Predictive Intervention (12-18 months)

**Goal**: Prevent problems before they occur.

| Prediction | Action | Human Involvement |
|------------|--------|-------------------|
| Demand spike predicted | Pre-order from supplier | Notification only |
| Supplier delay likely | Find alternative supplier | Approval for switch |
| Quality issue pattern | Pause supplier orders | Review before pause |
| Stockout imminent | Emergency reorder | Notification if under threshold |

### Step 4: Multi-Agent Coordination (18-24 months)

**Goal**: Agents collaborate on complex decisions.

```
Inventory Agent <-> Pricing Agent: Stock-based pricing adjustments
Inventory Agent <-> Support Agent: Real-time stock info in support chats
Inventory Agent <-> Fraud Agent: Hold suspicious bulk orders
Inventory Agent <-> Shipping Agent: Carrier selection based on urgency
```

**Guardrails**:
- Cross-agent decisions logged with full trace
- Any agent can flag for human review
- "Circuit breaker" if agents enter loop

### Step 5: Autonomous Operations (24+ months)

**Goal**: Full autonomy for defined scope with strict boundaries.

**What Stays Autonomous**:
- Stock monitoring and alerts
- Standard reorders under threshold
- Supplier selection from approved list
- Quality inspection (pass/fail)
- Customer stock responses

**What Always Needs Humans**:
- New supplier onboarding
- Contract changes
- Reorders over threshold
- Supplier dispute resolution
- Policy changes

### Autonomy Safety Framework

```python
class AutonomyGuardrails:
    """Enforce limits on autonomous agent actions."""

    HARD_LIMITS = {
        "max_single_order_value": 10000,
        "max_daily_order_value": 50000,
        "max_orders_per_hour": 20,
        "max_new_supplier_orders": 0,  # Never auto-order from new suppliers
        "max_dispute_auto_resolution": 500,
    }

    SOFT_LIMITS = {
        "preferred_approval_threshold": 5000,
        "alert_threshold_daily": 25000,
    }

    def check_action(self, action: dict) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        value = action.get("value", 0)
        action_type = action.get("type")

        # Hard limits are never bypassed
        if value > self.HARD_LIMITS["max_single_order_value"]:
            return False, "exceeds_hard_limit"

        if action_type == "new_supplier_order":
            return False, "new_supplier_requires_human"

        # Soft limits trigger review but don't block
        if value > self.SOFT_LIMITS["preferred_approval_threshold"]:
            self._request_review(action)

        return True, "allowed"

    def emergency_stop(self):
        """Global kill switch for all autonomous actions."""
        # Set feature flag
        # Alert all humans
        # Log reason
        pass
```

---

## Supplier Contract Facilitation

### What Agents CAN Automate

| Task | Automation Approach | Human Role |
|------|---------------------|------------|
| **Contract Renewal Reminders** | Date-based alerts | Review and sign |
| **Pricing Verification** | Compare PO price to contract | Approve discrepancies |
| **Volume Commitment Tracking** | Aggregate order history | Negotiate adjustments |
| **SLA Monitoring** | Track delivery performance | Discuss with supplier |
| **Document Organization** | Auto-file contracts by supplier | Retrieve when needed |
| **Clause Extraction** | NLP to identify key terms | Verify accuracy |
| **Compliance Checking** | Flag expiring certifications | Follow up |

### What Agents SHOULD NOT Automate

| Task | Why Not | Agent Support Instead |
|------|---------|----------------------|
| **Contract Negotiation** | Requires relationship, context | Prepare negotiation briefs |
| **Term Changes** | Legal implications | Highlight changed clauses |
| **Dispute Resolution** | Judgment required | Compile evidence |
| **New Supplier Approval** | Risk assessment | Score and summarize |
| **Payment Term Changes** | Cash flow impact | Model scenarios |

### Low-Level Contract Facilitation

```python
class ContractFacilitator:
    """Help humans manage supplier contracts more efficiently."""

    def extract_key_terms(self, contract_text: str) -> dict:
        """Extract actionable terms without LLM (regex + rules)."""
        import re

        terms = {}

        # Payment terms
        payment_match = re.search(r'net\s*(\d+)', contract_text.lower())
        if payment_match:
            terms['payment_days'] = int(payment_match.group(1))

        # Minimum order
        moq_match = re.search(r'minimum\s*(?:order|quantity)[:\s]*(\d+)', contract_text.lower())
        if moq_match:
            terms['minimum_order_qty'] = int(moq_match.group(1))

        # Lead time
        lead_match = re.search(r'lead\s*time[:\s]*(\d+)\s*(day|week)', contract_text.lower())
        if lead_match:
            days = int(lead_match.group(1))
            if 'week' in lead_match.group(2):
                days *= 7
            terms['lead_time_days'] = days

        # Warranty
        warranty_match = re.search(r'warranty[:\s]*(\d+)\s*(month|year)', contract_text.lower())
        if warranty_match:
            months = int(warranty_match.group(1))
            if 'year' in warranty_match.group(2):
                months *= 12
            terms['warranty_months'] = months

        return terms

    def generate_renewal_brief(self, supplier_id: str) -> dict:
        """Compile data for human contract renewal discussion."""
        return {
            "order_history": self._get_order_summary(supplier_id),
            "quality_metrics": self._get_quality_summary(supplier_id),
            "delivery_performance": self._get_delivery_summary(supplier_id),
            "dispute_history": self._get_disputes(supplier_id),
            "market_comparison": self._get_market_rates(supplier_id),
            "suggested_talking_points": self._generate_talking_points(supplier_id),
        }

    def _generate_talking_points(self, supplier_id: str) -> list[str]:
        """Rule-based generation of negotiation points."""
        points = []
        metrics = self._get_quality_summary(supplier_id)

        if metrics.get("on_time_rate", 1.0) < 0.9:
            points.append(f"Delivery performance at {metrics['on_time_rate']:.0%} - discuss improvement plan")

        if metrics.get("defect_rate", 0) > 0.02:
            points.append(f"Quality concerns: {metrics['defect_rate']:.1%} defect rate")

        if metrics.get("volume_growth", 0) > 0.2:
            points.append(f"Order volume up {metrics['volume_growth']:.0%} - request volume discount")

        return points
```

---

## Reducing GPU/LLM/API Token Reliance

### This is NOT a Noobish Question

This is actually a **sophisticated operational concern**. Here's why it matters:

| Cost Factor | Typical Monthly Cost | With Optimization |
|-------------|---------------------|-------------------|
| GPT-4 API calls | $500-2000 | $50-200 (90% reduction) |
| GPU compute | $200-1000 | $0-50 (CPU fallback) |
| Vision API | $100-500 | $10-50 (local models) |

### Token Reduction Strategies

```python
class TokenOptimizer:
    """Reduce LLM API usage through smart caching and routing."""

    def __init__(self, cache_backend):
        self.cache = cache_backend
        self.stats = {"cache_hits": 0, "api_calls": 0}

    def get_response(self, query: str, context: dict) -> str:
        # 1. Check semantic cache
        cache_key = self._semantic_hash(query, context)
        cached = self.cache.get(cache_key)
        if cached:
            self.stats["cache_hits"] += 1
            return cached

        # 2. Check if rule-based response is sufficient
        rule_response = self._try_rules(query, context)
        if rule_response:
            return rule_response

        # 3. Check if smaller model suffices
        complexity = self._estimate_complexity(query)
        if complexity < 0.3:
            response = self._call_cheap_model(query, context)
        else:
            response = self._call_main_model(query, context)

        self.stats["api_calls"] += 1
        self.cache.set(cache_key, response, ttl=3600)
        return response

    def _semantic_hash(self, query: str, context: dict) -> str:
        """Create cache key that groups similar queries."""
        # Normalize query (lowercase, remove punctuation, stem words)
        normalized = self._normalize(query)
        # Include only stable context keys
        stable_context = {k: context[k] for k in sorted(context.keys())
                         if k in ["sku", "category", "query_type"]}
        return hashlib.md5(f"{normalized}|{stable_context}".encode()).hexdigest()
```

### Computation Reduction Hierarchy

```
1. RULE-BASED (Cost: $0)
   └─ Deterministic logic, lookup tables, regex
   └─ Covers 70% of inventory queries

2. CACHED RESPONSES (Cost: ~$0)
   └─ Semantic similarity cache
   └─ TTL: 1-24 hours based on data volatility

3. STATISTICAL MODELS (Cost: CPU only)
   └─ sklearn, statsmodels, scipy
   └─ Demand forecasting, anomaly detection

4. LIGHTWEIGHT ML (Cost: CPU, ~$0.001/inference)
   └─ Small neural nets, quantized models
   └─ MobileNet, DistilBERT, TinyLLaMA

5. LOCAL LLM (Cost: ~$0.01/inference if GPU, $0 if cached)
   └─ Ollama with local models
   └─ LLaMA, Mistral, Phi-3

6. CLOUD API (Cost: $0.01-0.10/inference)
   └─ OpenAI, Anthropic, Google
   └─ Only for complex reasoning
```

### Embedding Alternatives (No GPU)

```python
# Instead of GPU-based embeddings, use:

# 1. TF-IDF (pure Python)
from sklearn.feature_extraction.text import TfidfVectorizer
vectorizer = TfidfVectorizer(max_features=1000)
embeddings = vectorizer.fit_transform(texts)

# 2. Hash-based embeddings (instant, no training)
from sklearn.feature_extraction.text import HashingVectorizer
hasher = HashingVectorizer(n_features=256)
embeddings = hasher.transform(texts)

# 3. Pre-computed embeddings (one-time cost)
# Store embeddings for your product catalog once
# Query with cosine similarity (pure NumPy)
```

---

## IOPs and Object Storage Considerations

### When to Use What

| Data Type | Storage | Why |
|-----------|---------|-----|
| **Transaction records** | PostgreSQL | ACID, relational queries |
| **Time-series metrics** | TimescaleDB | Efficient time-range queries |
| **Product images** | Object storage (S3/MinIO) | Large files, CDN-friendly |
| **CV inference results** | PostgreSQL JSONB | Structured, queryable |
| **Audit logs** | Append-only (object + index) | Immutable, compliance |
| **ML models** | Object storage | Large binary files |
| **Session data** | Redis | Fast access, TTL |
| **Search indexes** | Elasticsearch/Meilisearch | Full-text, faceted |

### IOPS Considerations

| Workload | IOPS Need | Solution |
|----------|-----------|----------|
| Stock level queries | Low (100s) | Standard SSD |
| Real-time inventory updates | Medium (1000s) | Provisioned IOPS |
| Stocktake reconciliation | Burst (10000s) | Auto-scaling or pre-provision |
| Image uploads | Low IOPS, high throughput | Object storage |
| Report generation | Batch, read-heavy | Read replicas |

### Object Storage Architecture for CV

```
/shopsquire-cv-bucket/
├── /incoming/                    # Temporary upload destination
│   └── {tenant_id}/{timestamp}_{hash}.jpg
├── /processed/                   # After CV analysis
│   └── {tenant_id}/{year}/{month}/{image_id}.jpg
├── /evidence/                    # Dispute evidence (long retention)
│   └── {tenant_id}/disputes/{dispute_id}/{image_id}.jpg
├── /models/                      # ML models
│   └── {model_name}/{version}/model.onnx
└── /thumbnails/                  # CDN-served thumbnails
    └── {tenant_id}/{image_id}_thumb.webp
```

### Non-Relational Data Patterns

```python
class HybridStorage:
    """Combine relational metadata with object storage for files."""

    def __init__(self, db_session, object_store):
        self.db = db_session
        self.objects = object_store

    def store_cv_result(self, tenant_id: str, image_bytes: bytes, result: dict):
        # 1. Store image in object storage
        image_id = str(uuid.uuid4())
        object_key = f"processed/{tenant_id}/{datetime.now():%Y/%m}/{image_id}.jpg"
        self.objects.put(object_key, image_bytes)

        # 2. Store metadata in PostgreSQL
        self.db.execute(
            """
            INSERT INTO cv_results (id, tenant_id, object_key, result_json, created_at)
            VALUES (:id, :tenant, :key, :result, NOW())
            """,
            {"id": image_id, "tenant": tenant_id, "key": object_key,
             "result": json.dumps(result)}
        )

        return image_id

    def get_cv_result(self, image_id: str) -> dict:
        # 1. Get metadata from PostgreSQL
        row = self.db.execute(
            "SELECT object_key, result_json FROM cv_results WHERE id = :id",
            {"id": image_id}
        ).fetchone()

        if not row:
            return None

        # 2. Generate presigned URL for image (don't fetch bytes)
        presigned_url = self.objects.presign(row["object_key"], expires=3600)

        return {
            "result": json.loads(row["result_json"]),
            "image_url": presigned_url
        }
```

---

## Career Development

### You're Demonstrating These Skills

| Skill | Evidence from Your Question |
|-------|----------------------------|
| **Systems Thinking** | Connecting inventory, suppliers, CV, email, contracts |
| **Cost Awareness** | GPU/LLM/API token concerns |
| **Security Mindset** | BEC/DMARC without prompting |
| **Modularity Focus** | "Clients can add client-specific CV later" |
| **Autonomy Design** | Asking about guardrails alongside automation |
| **Infrastructure Awareness** | IOPs, object storage questions |

### How to Strengthen Each Role

#### Operations Guy

| Skill to Build | How to Demonstrate |
|----------------|-------------------|
| **Incident Response** | Document runbooks, practice drills |
| **Capacity Planning** | Build forecasting dashboards |
| **Cost Optimization** | Track and reduce cloud spend |
| **Monitoring** | Set up Grafana, write alerting rules |
| **Compliance** | Implement audit logging, retention policies |

#### Business Process Guy

| Skill to Build | How to Demonstrate |
|----------------|-------------------|
| **Process Mapping** | Create BPMN diagrams for key workflows |
| **Requirements Gathering** | Document user stories with acceptance criteria |
| **KPI Definition** | Define and track business metrics |
| **Stakeholder Communication** | Write executive summaries |
| **Change Management** | Document rollout plans |

#### AI Architect

| Skill to Build | How to Demonstrate |
|----------------|-------------------|
| **Model Selection** | Justify why X model vs Y model |
| **Data Pipeline Design** | ETL, feature engineering |
| **MLOps** | Model versioning, monitoring, retraining |
| **Cost-Performance Tradeoffs** | Benchmark and document |
| **Responsible AI** | Bias detection, explainability |

#### AI Engineer

| Skill to Build | How to Demonstrate |
|----------------|-------------------|
| **Model Implementation** | Train, fine-tune, deploy models |
| **Optimization** | Quantization, pruning, caching |
| **Integration** | Connect models to production systems |
| **Testing** | Unit tests for ML components |
| **Debugging** | Profile and fix inference issues |

### Hireable Portfolio Pieces from ShopSquire

1. **"Built autonomous inventory agent with 50+ deterministic rules, achieving 80% automation with configurable guardrails"**

2. **"Implemented tiered ML inference system reducing API costs by 90% through caching, rule-based fallbacks, and model selection"**

3. **"Designed multi-factor supplier scoring using Bayesian reliability tracking with time decay"**

4. **"Created BEC detection system for supplier communications with DMARC/DKIM/SPF verification"**

5. **"Architected hybrid storage system combining PostgreSQL metadata with S3 object storage for CV evidence"**

---

## TOGAF Considerations

### TOGAF Architecture Development Method (ADM) Mapping

| TOGAF Phase | ShopSquire Consideration |
|-------------|-------------------------|
| **Preliminary** | Define architecture principles (modular, tenant-isolated, auditable) |
| **A: Architecture Vision** | "Autonomous retail operations with human-in-the-loop guardrails" |
| **B: Business Architecture** | Map inventory, supplier, customer processes |
| **C: Information Systems** | Data architecture (relational + object), application components |
| **D: Technology Architecture** | PostgreSQL, Redis, S3, Kubernetes |
| **E: Opportunities & Solutions** | Prioritize: rules first, then ML, then autonomy |
| **F: Migration Planning** | Phase 1-5 autonomy roadmap |
| **G: Implementation Governance** | Guardrails, approval workflows, audit logging |
| **H: Architecture Change Management** | Feature flags, A/B testing, gradual rollout |

### TOGAF Building Blocks for Inventory Agent

```
Architecture Building Blocks (ABBs):
├── Decision Engine ABB
│   └─ Rule evaluation, confidence scoring, routing
├── Supplier Integration ABB
│   └─ API connectors, contract storage, communication
├── CV Processing ABB
│   └─ Image intake, analysis pipeline, result storage
├── Audit Trail ABB
│   └─ Decision logging, trace events, compliance
└── Human-in-Loop ABB
    └─ Approval workflows, escalation, overrides

Solution Building Blocks (SBBs):
├── InventoryAgent (Python class)
├── SupplierReliabilityTracker (Python class)
├── ManagedCVProvider (Python class)
├── TicketingAgent (Python class)
└── PostgreSQL + Redis + S3 (infrastructure)
```

### Key TOGAF Principles for AI Systems

1. **Principle: Explainability**
   - Every automated decision must have a human-readable rationale
   - Audit logs capture input, context, reasoning, action

2. **Principle: Graceful Degradation**
   - System continues operating if ML components fail
   - Fallback to rules, then to human decision

3. **Principle: Human Override**
   - Any automated decision can be reversed by authorized human
   - Override is logged but always permitted

4. **Principle: Bounded Autonomy**
   - Hard limits on what agents can do without approval
   - Limits are configurable but have defaults

5. **Principle: Tenant Isolation**
   - Client data never mixed
   - Models can be tenant-specific or shared

### TOGAF Resources to Study

| Resource | Why |
|----------|-----|
| **TOGAF 10 Foundation** | Official certification, widely recognized |
| **ArchiMate 3.2** | Modeling language for enterprise architecture |
| **Business Architecture Guild BIZBOK** | Deeper on business capability mapping |
| **AWS Well-Architected Framework** | Practical cloud architecture patterns |
| **Google MLOps Whitepaper** | ML-specific architecture patterns |

---

## Summary: Your Action Items

### Immediate (This Week)
- [ ] Implement 10 core stock interaction rules
- [ ] Add DMARC/DKIM check to supplier email workflow
- [ ] Set up basic CV confidence thresholds

### Short-Term (This Month)
- [ ] Complete 50 stock rules implementation
- [ ] Implement supplier reliability decay model
- [ ] Create contract term extraction (regex-based)
- [ ] Set up object storage for CV images

### Medium-Term (This Quarter)
- [ ] Implement tiered inference with caching
- [ ] Build confidence-based escalation router
- [ ] Create supplier dispute workflow
- [ ] Document TOGAF building blocks

### Long-Term (This Year)
- [ ] Achieve Level 3 autonomy for routine operations
- [ ] Reduce API costs by 90%
- [ ] Build portfolio case studies
- [ ] Consider TOGAF certification

---

*Document generated for ShopSquire inventory agent enhancement planning.*
*This analysis demonstrates: systems architecture, ML engineering, business process design, and operational thinking.*
