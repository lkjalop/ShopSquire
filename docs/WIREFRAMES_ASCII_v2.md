# ShopSquire Wireframes (ASCII, Corrected)

Generated: 2026-01-24

Purpose: Clear, production-oriented wireframes covering storefront NLP states, cart and checkout flows, the decision-trace gear popup, and merchant/admin dashboards.

---

## Storefront Overview (Desktop)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ SHOPSQUIRE                                         [Search products...]   🛒 Cart(2)   👤 Login │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                              │
│ Category: Laptops  [Filters: Price▼ RAM▼ Brand▼]                                             │
│                                                                                              │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                                        │
│ │  [Image]     │  │  [Image]     │  │  [Image]     │                                        │
│ │  Dell XPS 13 │  │ ThinkPad X1  │  │ MacBook Air  │                                        │
│ │  $899  ★★★★☆ │  │ $1,099 ★★★★★ │  │ $1,299 ★★★★☆ │                                        │
│ │ [Add to Cart]│  │[Add to Cart] │  │[Add to Cart] │                                        │
│ └──────────────┘  └──────────────┘  └──────────────┘                                        │
│                                                                                              │
│                                             ┌──────────────┐                                 │
│                                             │     🤖       │ ◄── Floating assistant (collapsed)│
│                                             │   Ask Me!    │     bottom-right, 72×72          │
│                                             └──────────────┘                                 │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

States at a glance:
- Default: Floating button only (non-intrusive).
- Product Query: Expanded overlay with intents, product cards, and comparisons.
- Cart-Aware: Suggestions/upsells informed by current cart.
- Checkout Assist: Explains shipping, returns, discounts, with policy-safe actions.

---

## NLP Assistant States & Transitions

### 1) Default (Collapsed)
```
┌──────────────┐
│     🤖       │
│   Ask Me!    │  Tooltip on hover: "Compare, find deals, explain differences"
└──────────────┘
```

Triggers to expand:
- Hover a product >3s, type in search without clicking a result, add-to-cart event, or user click.

### 2) Product Query Mode (Expanded Overlay)
```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 💬 ShopSquire AI Assistant                                                     [× Close] │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 🤖 What matters most today?  [Performance] [Battery] [Budget] [Work] [Gaming]           │
│ ─────────────────────────────────────────────────────────────────────────────────────── │
│ 👤 You: "Show laptops under $1000 with 16GB RAM"                                        │
│                                                                                          │
│ 🤖 I found 3 solid matches:                                                              │
│  ┌────────────────────────────┐  ┌────────────────────────────┐  ┌─────────────────────┐ │
│  │ 🏆 ThinkPad X1   $1,099 ⚠  │  │ 💰 Dell XPS 13  $899      │  │ HP Envy 14   $799  │ │
│  │ 18h batt, 16GB, 1TB        │  │ 12h batt, 16GB, 512GB     │  │ 10h batt, 8GB      │ │
│  │ [Add $989 (10% off)]       │  │ [Add to Cart] [Compare]   │  │ [Details]          │ │
│  └────────────────────────────┘  └────────────────────────────┘  └─────────────────────┘ │
│                                                                                          │
│ [Show Comparison Table]  [Refine Filters]  [Explain differences]                          │
│                                                                                          │
│ Type your message...                                               [🎤] [📎]        [Send] │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

Notes:
- “⚠” indicates a near-budget item with dynamic offer (policy-gated discount).
- Comparison table opens in-place; product cards remain interactive.

### 3) Cart-Aware Mode (Overlay + Sidebar)
```
┌──────────────────────────────────────────┬──────────────────────────────────────────────┐
│ 💬 Chat                                   │ 🎯 Cart-aware suggestions                    │
├──────────────────────────────────────────┤ ├────────────────────────────────────────────┤
│ 🤖 I see ThinkPad X1 in your cart.        │ Accessories for ThinkPad X1:                 │
│ Want a sleeve and USB-C hub?              │ • Sleeve ($29)  [Add]                        │
│                                           │ • USB-C hub ($49) [Add]                      │
│ 👤 Compare battery life vs Dell XPS 13     │ Savings today: Bundle 10% → $70             │
│                                           │ [Add Bundle]                                 │
│ [Show comparison] [Apply bundle]          │                                              │
└──────────────────────────────────────────┴──────────────────────────────────────────────┘
```

### 4) Checkout Assist (Policy-safe)
```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 💬 Checkout Help                                                             [× Close]  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 🤖 Summary: 2 items, subtotal $2,198, tax est $176, total $2,374                           │
│ Shipping: 2-day available. Returns: 30-day policy.                                         │
│ Discounts: VIP 10% possible → requires approval.                                           │
│ [Request approval] [Proceed to payment] [Explain fees]                                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

Outcome after approval request:
- Pending badge in cart, applied automatically on approval with audit link to decision.

---

## Decision Trace (Gear Popup)

Access: Small gear icon on assistant header or near recommended action buttons.

### Gear Icon Placement
```
💬 ShopSquire AI Assistant                               [⚙ Decision Trace]   [×]
```

### Decision Trace Overlay (Tabbed)
```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ ⚙ Decision Trace: rec-7f2a                                                 [Export JSON] [×] │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ [Summary] [Inputs] [Context] [Model Evidence] [Policy Gate] [Actions]                      │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ Summary                                                                                   │
│ ───────────────────────────────────────────────────────────────────────────────────────   │
│ • Outcome: Recommend ThinkPad X1; Offer 10% off (tentative)                               │
│ • Confidence: 0.92   • Latency: 487ms   • Policy: v1.2                                    │
│ • Cart impact: +$989 discounted line if approved                                          │
│                                                                                           │
│ Timeline                                                                                  │
│  ┌─► Parse intent → Build constraints → Retrieve candidates → Score → Explain → Policy ┐  │
│  │   12ms            64ms               132ms                68ms     24ms       45ms   │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                           │
│ Inputs                                                                                     │
│ ───────────────────────────────────────────────────────────────────────────────────────   │
│ • User text (normalized): "laptops under $1000 16GB"                                      │
│ • Flags: locale=en-US, device=desktop, session prefs: battery-high                         │
│ • Security: control chars stripped, injection patterns negative                            │
│                                                                                           │
│ Context                                                                                    │
│ ───────────────────────────────────────────────────────────────────────────────────────   │
│ • Catalog snapshot: 5 candidates (IDs: p-101, p-203, p-355, p-411, p-578)                  │
│ • Reviews, stock, price window, prior cart items                                           │
│                                                                                           │
│ Model Evidence                                                                             │
│ ───────────────────────────────────────────────────────────────────────────────────────   │
│ • Scoring: ThinkPad X1 = 0.91  (battery + rating); Dell XPS 13 = 0.86 (budget)            │
│ • Explanations: ✓RAM ✓Battery ✓Rating; Dell: ✓Budget ✓RAM                                 │
│ • Comparison table diff: Battery +6h, Price +$200                                          │
│                                                                                           │
│ Policy Gate                                                                                │
│ ───────────────────────────────────────────────────────────────────────────────────────   │
│ • Discount offer 10% → requires approval for non-VIP                                       │
│ • Margin ≥ 15% → PASS (18%); Cap ≤ 30% → PASS; Amount ≥ $250 → REVIEW                      │
│ • Action: Queue approval; render offer as pending                                          │
│                                                                                           │
│ Actions                                                                                    │
│ ───────────────────────────────────────────────────────────────────────────────────────   │
│ • [Approve] [Reject] [Escalate] (admin-only)                                               │
│ • [Link: Decision Logs] [Link: Security Events]                                            │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

Mobile gear popup: Fullscreen with stacked tabs (Summary at top, accordion sections).

---

## Cart (Overlay)

```
┌───────────────────────────────────────────────────────────────┐
│ 🛒 Your Cart                                           [×]     │
├───────────────────────────────────────────────────────────────┤
│ 1) ThinkPad X1 Carbon                          $1,099          │
│    Qty [1▼]   [Remove]   ⚙ Trace                                                │
│    Pending: 10% off (awaiting approval)                                         │
│                                                               │
│ 2) Dell XPS 13 Plus                              $899          │
│    Qty [1▼]   [Remove]                                          │
│                                                               │
│ ───────────────────────────────────────────────────────────    │
│ Accessories: Sleeve ($29) [Add]  USB-C hub ($49) [Add]         │
│ Subtotal: $1,998   Tax: $160   Total: $2,158                   │
│ [Continue Shopping]                            [Checkout]      │
└───────────────────────────────────────────────────────────────┘
```

---

## Checkout (Desktop)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Checkout                                                                                      │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Shipping Address     │ Payment Method            │ Order Summary                               │
│ ┌──────────────────┐ │ ┌──────────────────────┐ │ ┌─────────────────────────────────────────┐ │
│ │ [Name]           │ │ │ [Card number]        │ │ │ ThinkPad X1            $1,099           │ │
│ │ [Street]         │ │ │ [Exp] [CVC]          │ │ │ Dell XPS 13+             $899           │ │
│ │ [City, State ZIP]│ │ │ [Billing same] [✓]   │ │ │ Discount (pending)       -$110           │ │
│ └──────────────────┘ │ └──────────────────────┘ │ │ Total                   $1,888           │ │
│                                                  │ └─────────────────────────────────────────┘ │
│ [Back]                                         [Place Order]                                   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Assistant inline tip: “Returns are 30 days; discount will apply automatically if approved.”

---

## Merchant Dashboard (Owner)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ SHOPSQUIRE MERCHANT                                      [owner@merchant]  🔔 3  ⚙️  [Logout]   │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [Overview] [Orders] [Products] [Decisions] [Approvals] [Security] [Analytics]                  │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 🚨 Alerts (Today)                                                                              │
│ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ 🔴 Prompt injection blocked   Risk 78   [View] [Block IP]                                  │ │
│ │ 🟡 Discount approval pending   Alice Smith   25% ($312)   [Approve] [Reject]               │ │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                  │
│ 📈 KPIs (Live)                                                                                   │
│ ┌────────────────────┬────────────────────┬────────────────────┬──────────────────────────────┐ │
│ │ 💰 Revenue   $42K  │ 🛒 Orders   247    │ 🤖 Autonomy  78%   │ 🛡️ Security ✓  1H / 3W       │ │
│ │ ↑ 12% vs yday      │ ↑ 8% vs yday      │ ↑ 5% vs last week │ [View Events]                │ │
│ └────────────────────┴────────────────────┴────────────────────┴──────────────────────────────┘ │
│                                                                                                  │
│ 📦 Inventory Alerts     ⚠ 12 low-stock items  [View] [Auto-Reorder]                              │
│                                                                                                  │
│ 🤖 Decision Logs (Recent)                                                                        │
│ ┌──────────────────────────────────────────────────────────────┬───────────────────────────────┐ │
│ │ ID        Status   Action         Policy   Confidence   Time  │ [Filter ▼] [Export CSV]      │ │
│ │ rec-7f2a  executed recommend      v1.2     0.92        10:42 │ [Open Detail]                │ │
│ │ prc-88bb  pending  discount(10%)  v1.2     0.81        10:43 │ [Open Detail]                │ │
│ └──────────────────────────────────────────────────────────────┴───────────────────────────────┘ │
│                                                                                                  │
│ 🔗 Quick Actions: [PowerBI] [Feature Flags] [Export Audit Logs] [Reload Policy]                 │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Decision detail opens the same “Decision Trace” overlay with admin actions enabled.

---

## Admin Dashboard (Unified Control Center)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ SHOPSQUIRE ADMIN                                        [kevin@admin]  🔔 3  ⚙️  [Logout]      │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [Overview] [Agent Decisions] [Security] [E-commerce] [Accounting] [System Health]              │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 🚨 Critical & Pending                                                                           │
│ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ 🔴 High Risk: AML.T0043   Score: 78   2m ago   [View] [Block IP] [Escalate]                │ │
│ │ 🟡 Approval: 25% discount   Alice Smith   $1,248→$936   [Approve] [Reject]                 │ │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                  │
│ 📈 Live KPIs                                                                                     │
│ ┌────────────────────┬────────────────────┬────────────────────┬────────────────────┬──────────┐ │
│ │ 💰 Revenue  $42K   │ 🛒 Orders   247    │ 🤖 Autonomy 78%    │ 🛡️ Sec ✓ 1H/3W    │ Stock ⚠  │ │
│ └────────────────────┴────────────────────┴────────────────────┴────────────────────┴──────────┘ │
│                                                                                                  │
│ 📊 Charts: Revenue (7d) | Decisions (24h) | Threats (30d) | Top Products (today)                │
│                                                                                                  │
│ 🔗 Actions: [Export Logs] [Reload Policy] [Feature Flags] [Open PowerBI] [Test Alerts]          │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Admin Dashboard (Dual-Pane Security Focus)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ SHOPSQUIRE ADMIN                                        [kevin@admin]  🔔 3  ⚙️  [Logout]     │
├──────────────────────────────────────────────┬───────────────────────────────────────────────┤
│ E-commerce & Ops                             │ Security & Compliance                         │
├──────────────────────────────────────────────┼───────────────────────────────────────────────┤
│ KPIs, Orders, Inventory, Decisions           │ Security status, Live threat feed, Compliance │
│                                              │ Alerts, Evidence export                       │
│ [PowerBI] [Export] [Flags]                   │ [View Threat Map] [Export Report]             │
└──────────────────────────────────────────────┴───────────────────────────────────────────────┘
```

---

## Mobile Variants

Key differences:
- Assistant expands to fullscreen overlay; tabs become accordions; swipeable product cards.
- Dashboards use stacked KPI cards with bottom navigation; live feed collapses into a list.

---

## Notes

- Non-intrusive assistant: collapsed by default; intent-based triggers only.
- Decision Trace gear popup is available in chat and admin/merchant decision details.
- Cart and checkout integrate policy gates with clear pending states and audit links.
- ASCII designed for clarity; final UI should implement progressive disclosure, accessibility, and responsive patterns.
