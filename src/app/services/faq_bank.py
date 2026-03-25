from __future__ import annotations

import re
from typing import Dict, List, Tuple

_FAQ_STOPWORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "how", "i", "if",
    "is", "it", "my", "of", "on", "or", "the", "to", "what", "when", "with",
    "you", "your",
}


FAQ_BANK: List[Dict[str, object]] = [
    {"q": "What is your return policy?", "a": "Returns are accepted within 14 days for unused items in original packaging.", "tags": ["return", "policy"]},
    {"q": "How long do refunds take?", "a": "Refunds typically post within 3-5 business days after approval.", "tags": ["refund", "timeline"]},
    {"q": "Can I exchange my item?", "a": "Yes. Exchanges are available within 14 days for the same item or equivalent value.", "tags": ["exchange", "return"]},
    {"q": "How do I start a return?", "a": "Open your order and select “Request return” to generate a label.", "tags": ["return", "label"]},
    {"q": "Do you offer free returns?", "a": "Free returns are available for damaged or incorrect items; otherwise return shipping may apply.", "tags": ["return", "shipping"]},
    {"q": "Where is my order?", "a": "You can track your order from the Orders page using your tracking number.", "tags": ["order", "tracking"]},
    {"q": "How do I track my shipment?", "a": "Use the tracking link sent to your email or SMS after dispatch.", "tags": ["tracking", "shipping"]},
    {"q": "Do you ship internationally?", "a": "We currently ship within the US and select regions. Check the Shipping page for details.", "tags": ["shipping", "international"]},
    {"q": "How long does shipping take?", "a": "Standard shipping takes 3-5 business days; expedited options are available at checkout.", "tags": ["shipping", "delivery"]},
    {"q": "Can I change my shipping address?", "a": "Address changes are possible before the order ships. Contact support quickly.", "tags": ["address", "order"]},
    {"q": "Can I cancel my order?", "a": "Orders can be canceled before they ship. Once shipped, you can request a return.", "tags": ["cancel", "order"]},
    {"q": "What payment methods do you accept?", "a": "We accept major credit cards, PayPal, and supported digital wallets.", "tags": ["payment", "methods"]},
    {"q": "Do you offer financing?", "a": "Financing options may be available at checkout for eligible purchases.", "tags": ["financing", "payment"]},
    {"q": "Is my payment information secure?", "a": "Yes. Payments are processed via PCI-compliant providers.", "tags": ["payment", "security"]},
    {"q": "How do I apply a promo code?", "a": "Enter your promo code at checkout in the discount field.", "tags": ["promo", "discount"]},
    {"q": "Why was my promo code rejected?", "a": "Promo codes may be expired, ineligible, or already used. Check the terms.", "tags": ["promo", "discount"]},
    {"q": "Do you price match?", "a": "We review price match requests on eligible items within 7 days of purchase.", "tags": ["price", "match"]},
    {"q": "What is the warranty period?", "a": "Most products include a 1-year manufacturer warranty unless stated otherwise.", "tags": ["warranty"]},
    {"q": "How do I register a warranty?", "a": "Register your product using the manufacturer link in your order details.", "tags": ["warranty", "register"]},
    {"q": "What if my item arrived damaged?", "a": "Report damage within 48 hours and upload photos for fast resolution.", "tags": ["damaged", "complaint"]},
    {"q": "What if I received the wrong item?", "a": "We will replace incorrect items at no cost. Start a return request.", "tags": ["wrong item", "return"]},
    {"q": "How do I contact support?", "a": "Use the Help & Support page or start a chat for fastest response.", "tags": ["support", "contact"]},
    {"q": "What are your support hours?", "a": "Support is available 7 days a week, 8am–8pm local time.", "tags": ["support", "hours"]},
    {"q": "Can I chat with a human agent?", "a": "Yes. If the assistant can’t resolve your issue, you can request human support.", "tags": ["human", "support"]},
    {"q": "How do I update my account email?", "a": "Go to Account Settings and update your email address.", "tags": ["account", "email"]},
    {"q": "I forgot my password. What should I do?", "a": "Use the “Forgot Password” link to reset your password securely.", "tags": ["account", "password"]},
    {"q": "How do I view my order history?", "a": "Your order history is available in the Orders section.", "tags": ["order", "history"]},
    {"q": "Where can I find my invoice?", "a": "Invoices are available in your order details page.", "tags": ["invoice", "order"]},
    {"q": "Do you charge sales tax?", "a": "Sales tax is applied based on your shipping address.", "tags": ["tax"]},
    {"q": "Why did my order fail?", "a": "Payment or inventory issues can cause failures. Try again or contact support.", "tags": ["order", "payment"]},
    {"q": "How do I reorder an item?", "a": "Open a past order and click “Reorder” to add items to your cart.", "tags": ["reorder", "order"]},
    {"q": "Can I split shipments?", "a": "We may split shipments based on inventory availability.", "tags": ["shipping", "split"]},
    {"q": "What does backorder mean?", "a": "Backorder means the item is temporarily out of stock but can be reserved.", "tags": ["backorder", "inventory"]},
    {"q": "How do I check product availability?", "a": "Availability appears on the product page and updates in real time.", "tags": ["availability", "inventory"]},
    {"q": "Are there bulk purchase discounts?", "a": "Bulk pricing is available for qualified orders. Contact sales.", "tags": ["bulk", "discount"]},
    {"q": "How do I file a complaint?", "a": "Use the Complaints page to submit details and upload evidence.", "tags": ["complaint", "support"]},
    {"q": "Can I upload photos for a refund request?", "a": "Yes, you can upload photos or videos to help validate your claim.", "tags": ["cv", "refund"]},
    {"q": "What happens after I submit a complaint?", "a": "Your case is reviewed, and you’ll receive updates and a decision.", "tags": ["complaint", "status"]},
    {"q": "How do I check complaint status?", "a": "Use your case ID on the status page to see updates.", "tags": ["complaint", "status"]},
    {"q": "Why is my request under review?", "a": "Some requests require human review due to policy or risk signals.", "tags": ["review", "policy"]},
    {"q": "What is a decision trace?", "a": "A decision trace shows the reasoning and policies used for a decision.", "tags": ["trace", "decision"]},
    {"q": "Do you store my personal data?", "a": "We store minimal data required to fulfill orders and comply with policies.", "tags": ["privacy", "data"]},
    {"q": "How do I delete my data?", "a": "You can request data deletion from the Privacy page.", "tags": ["privacy", "delete"]},
    {"q": "Can I opt out of marketing emails?", "a": "Yes, use the unsubscribe link in any email or update preferences.", "tags": ["marketing", "email"]},
    {"q": "What is your return window?", "a": "The return window is 14 days from delivery for eligible items.", "tags": ["return", "window"]},
    {"q": "Do you offer extended warranties?", "a": "Extended warranty options may be offered at checkout for select items.", "tags": ["warranty", "extended"]},
    {"q": "How do I report fraud?", "a": "Report suspected fraud via the Help page or security contact form.", "tags": ["fraud", "security"]},
    {"q": "Why is my account locked?", "a": "Accounts may be locked after suspicious activity; contact support to resolve.", "tags": ["account", "security"]},
    {"q": "Can I use multiple payment methods?", "a": "Split payments are not supported at this time.", "tags": ["payment"]},
    {"q": "Do you support gift cards?", "a": "Gift cards can be applied at checkout if available for your region.", "tags": ["gift", "payment"]},
    {"q": "How do I update my phone number?", "a": "Update your phone number in Account Settings.", "tags": ["account", "phone"]},

    # ── Physical damage & repair ──────────────────────────────────────────────
    {"q": "My laptop screen is cracked. What are my options?",
     "a": "Upload a clear photo of the damage so we can assess it. If your device is within the warranty period and the damage qualifies, we'll arrange repair or replacement. For accidental damage, out-of-warranty repair pricing applies.",
     "tags": ["repair", "screen", "cracked", "damage", "warranty"]},
    {"q": "My laptop screen has a crack. Is it covered by warranty?",
     "a": "Standard manufacturer warranties cover manufacturing defects, not accidental damage. If your screen cracked from a fall or impact, it is typically not covered unless you have an accidental damage protection plan.",
     "tags": ["screen", "cracked", "warranty", "damage"]},
    {"q": "My laptop won't turn on. What do I do?",
     "a": "Try a hard reset: hold the power button for 10–15 seconds, then release and press again. If it still won't turn on, it may be a battery or motherboard fault. Contact support with your order number for a warranty or repair assessment.",
     "tags": ["repair", "power", "wont turn on", "dead", "not starting"]},
    {"q": "My laptop is physically damaged. Can I get it repaired?",
     "a": "Upload photos of the damage and share your order details. We can assess whether it qualifies for warranty repair, paid repair, or a replacement recommendation.",
     "tags": ["repair", "physical", "damage", "broken"]},
    {"q": "My laptop hinge is broken. Is that covered?",
     "a": "Hinge damage from normal use (not a drop) may be covered as a manufacturing defect. Upload a photo and your purchase date and we'll assess eligibility.",
     "tags": ["repair", "hinge", "broken", "warranty"]},
    {"q": "My laptop keyboard is not working. What should I do?",
     "a": "If keys are stuck or unresponsive, first try cleaning with compressed air. If the issue persists and the laptop is under warranty, contact support — keyboard faults are commonly covered as manufacturing defects.",
     "tags": ["repair", "keyboard", "not working", "keys", "broken"]},
    {"q": "My laptop battery drains very fast. Is that covered by warranty?",
     "a": "Battery degradation below 80% capacity within the warranty period is typically covered. Contact us with your purchase date and battery health reading (from Settings → System → Battery) for an assessment.",
     "tags": ["battery", "drain", "warranty", "repair", "fast drain"]},
    {"q": "My laptop is overheating. What should I do?",
     "a": "Ensure vents are clear of dust and the laptop is on a hard surface. If it still overheats under light use, it may be a thermal paste or fan fault — both are typically covered under warranty.",
     "tags": ["repair", "overheating", "hot", "fan", "thermal"]},
    {"q": "My laptop got wet. Is liquid damage covered?",
     "a": "Liquid damage is not covered by standard manufacturer warranties. However, contact support quickly — acting within 24 hours can sometimes save the device. Upload photos and describe what liquid it was.",
     "tags": ["repair", "liquid", "water", "wet", "spill", "damage"]},

    # ── Software failures & BSOD ─────────────────────────────────────────────
    {"q": "My laptop shows a blue screen of death (BSOD). What do I do?",
     "a": "A BSOD usually means a driver, RAM, or Windows system file issue. Note the error code shown on screen (e.g. WHEA_UNCORRECTABLE_ERROR, MEMORY_MANAGEMENT). Restart and check for Windows Updates. If it keeps happening, contact support with the error code — this may qualify for a warranty claim.",
     "tags": ["bsod", "blue screen", "blue screen of death", "stop code", "repair", "software"]},
    {"q": "My laptop keeps crashing with a blue screen. How do I fix it?",
     "a": "Repeated BSODs often point to a driver conflict, failing RAM, or a corrupted Windows installation. Try: (1) Update all drivers, (2) Run Windows Memory Diagnostic, (3) Check Reliability History in Control Panel. If it persists, contact support with the BSOD stop code.",
     "tags": ["bsod", "blue screen", "crashing", "stop code", "fix", "repair"]},
    {"q": "My laptop shows WHEA_UNCORRECTABLE_ERROR. What does it mean?",
     "a": "WHEA_UNCORRECTABLE_ERROR usually indicates a hardware fault — often the CPU, RAM, or storage. This is commonly covered under warranty. Contact support with your purchase date and we'll arrange a diagnostic.",
     "tags": ["bsod", "whea", "stop code", "hardware fault", "repair", "warranty"]},
    {"q": "My laptop shows MEMORY_MANAGEMENT blue screen. What do I do?",
     "a": "MEMORY_MANAGEMENT BSODs often mean faulty or incompatible RAM. Run Windows Memory Diagnostic (search in Start Menu). If errors are found, this is a warranty-eligible hardware fault.",
     "tags": ["bsod", "memory", "ram", "stop code", "repair", "blue screen"]},
    {"q": "Windows won't load on my laptop. What can I do?",
     "a": "If Windows won't boot, try Startup Repair: restart and hold Shift while clicking Restart → Troubleshoot → Advanced Options → Startup Repair. If that fails, contact support — we can guide you through a reinstall or arrange a warranty repair.",
     "tags": ["windows", "boot", "repair", "software", "not loading", "startup"]},
    {"q": "My laptop is stuck on the loading screen. What do I do?",
     "a": "Hold the power button to force shutdown, then restart. If it keeps getting stuck, boot into Safe Mode (hold Shift + F8 on startup) and run a disk check. Contact support if the issue persists.",
     "tags": ["loading", "stuck", "boot", "repair", "software"]},
    {"q": "My laptop is running very slowly. How do I fix it?",
     "a": "Slowness can be caused by a full storage drive, too many startup programs, or malware. Try: (1) Free up disk space, (2) Disable startup apps in Task Manager, (3) Run a malware scan. If it's still sluggish on a new laptop, it may be a hardware issue covered by warranty.",
     "tags": ["slow", "performance", "repair", "sluggish", "freeze"]},
    {"q": "How do I reinstall Windows on my laptop?",
     "a": "You can reinstall Windows via Settings → System → Recovery → Reset this PC. Choose 'Keep my files' to reinstall without losing data. For a clean install, you'll need a USB bootable drive. Contact support if you need help.",
     "tags": ["windows", "reinstall", "reset", "software", "repair"]},

    # ── Extended warranty & protection ────────────────────────────────────────
    {"q": "Does my warranty cover accidental damage?",
     "a": "Standard manufacturer warranties cover manufacturing defects only, not accidental damage (drops, spills). Accidental Damage Protection is available as an optional add-on at checkout for select products.",
     "tags": ["warranty", "accidental", "damage", "cover", "protection"]},
    {"q": "How do I claim a warranty repair?",
     "a": "Contact support with your order number, purchase date, and a description (or photo) of the fault. We'll assess eligibility and arrange repair, replacement, or a manufacturer RMA.",
     "tags": ["warranty", "claim", "repair", "rma", "return"]},
    {"q": "What is the warranty claim process?",
     "a": "Start by contacting support with your order number, purchase date, photos if relevant, and the fault description. We'll confirm coverage and arrange repair, replacement, or a manufacturer RMA.",
     "tags": ["warranty", "claim", "process", "repair", "rma", "support"]},
    {"q": "My laptop is 6 months old and has a hardware fault. Am I covered?",
     "a": "Yes — most laptops carry a minimum 12-month manufacturer warranty, so a fault at 6 months is almost certainly covered. Contact support with your order number.",
     "tags": ["warranty", "hardware fault", "covered", "repair", "6 months"]},
    {"q": "How long is the standard warranty on laptops?",
     "a": "Most laptops include a 1-year manufacturer warranty. Some brands offer 2-year coverage. Extended warranty plans can add up to 3 additional years.",
     "tags": ["warranty", "period", "length", "laptop", "how long"]},
    {"q": "Can I extend my warranty after purchase?",
     "a": "Extended warranty plans may be available for purchase after the original sale date, usually within 30–90 days of purchase. Contact support to check eligibility.",
     "tags": ["warranty", "extended", "after purchase", "extend"]},
    {"q": "My laptop has a dead pixel. Is it under warranty?",
     "a": "Dead pixel policies vary by manufacturer. Most cover screens with 3+ dead pixels in the centre of the display. Contact support with a photo and your purchase date.",
     "tags": ["dead pixel", "screen", "warranty", "repair", "display"]},
]


# ── Policy overlay for the 20 most decision-critical FAQ entries ──────────────
# Keys: substring of the FAQ question (lowercase match).
# Fields injected:
#   policy_rule          - governing policy name
#   confidence_threshold - min orchestrator confidence to auto-resolve
#   fraud_gate           - if True: block auto-resolve when fraud_score > 50
#   nqe_required_fields  - fields NQE must collect before answer is sent
#   autonomy_tier        - default tier: "auto" | "hold" | "escalate"
#   escalate_if          - human-readable escalation condition
_FAQ_POLICY_OVERLAY: Dict[str, Dict] = {
    "return policy": {
        "policy_rule": "return_policy_v1",
        "confidence_threshold": 0.80,
        "fraud_gate": True,
        "nqe_required_fields": [],
        "autonomy_tier": "auto",
        "escalate_if": "item not in original packaging OR outside 14-day window",
    },
    "start a return": {
        "policy_rule": "return_initiation_v1",
        "confidence_threshold": 0.75,
        "fraud_gate": True,
        "nqe_required_fields": ["order_id"],
        "autonomy_tier": "auto",
        "escalate_if": "no matching order found for uid+sku",
    },
    "exchange my item": {
        "policy_rule": "exchange_policy_v1",
        "confidence_threshold": 0.75,
        "fraud_gate": True,
        "nqe_required_fields": ["order_id"],
        "autonomy_tier": "auto",
        "escalate_if": "outside 14-day window OR high-value item",
    },
    "arrived damaged": {
        "policy_rule": "damage_claim_v1",
        "confidence_threshold": 0.70,
        "fraud_gate": True,
        "nqe_required_fields": ["order_id", "damage_photo"],
        "autonomy_tier": "hold",
        "escalate_if": "CV damage not detected OR fraud_score > 50",
    },
    "wrong item": {
        "policy_rule": "wrong_item_v1",
        "confidence_threshold": 0.75,
        "fraud_gate": True,
        "nqe_required_fields": ["order_id", "photo"],
        "autonomy_tier": "hold",
        "escalate_if": "CV product type does not match order SKU",
    },
    "price match": {
        "policy_rule": "price_match_v1",
        "confidence_threshold": 0.80,
        "fraud_gate": False,
        "nqe_required_fields": ["competitor_url", "order_id"],
        "autonomy_tier": "hold",
        "escalate_if": "competitor price not verifiable OR outside 7-day window",
    },
    "cancel my order": {
        "policy_rule": "order_cancel_v1",
        "confidence_threshold": 0.85,
        "fraud_gate": False,
        "nqe_required_fields": ["order_id"],
        "autonomy_tier": "auto",
        "escalate_if": "order already shipped",
    },
    "claim a warranty repair": {
        "policy_rule": "warranty_claim_v1",
        "confidence_threshold": 0.70,
        "fraud_gate": True,
        "nqe_required_fields": ["order_id", "purchase_date", "fault_description"],
        "autonomy_tier": "hold",
        "escalate_if": "outside warranty period OR liquid damage detected",
    },
    "warranty claim process": {
        "policy_rule": "warranty_claim_v1",
        "confidence_threshold": 0.70,
        "fraud_gate": True,
        "nqe_required_fields": ["order_id", "purchase_date"],
        "autonomy_tier": "hold",
        "escalate_if": "outside warranty period",
    },
    "accidental damage": {
        "policy_rule": "accidental_damage_v1",
        "confidence_threshold": 0.65,
        "fraud_gate": True,
        "nqe_required_fields": ["order_id", "damage_photo"],
        "autonomy_tier": "escalate",
        "escalate_if": "always requires human review for accidental damage claims",
    },
    "liquid damage": {
        "policy_rule": "liquid_damage_v1",
        "confidence_threshold": 0.60,
        "fraud_gate": True,
        "nqe_required_fields": ["order_id", "damage_photo", "incident_time"],
        "autonomy_tier": "escalate",
        "escalate_if": "liquid damage always escalates to human review",
    },
    "screen is cracked": {
        "policy_rule": "physical_damage_v1",
        "confidence_threshold": 0.65,
        "fraud_gate": True,
        "nqe_required_fields": ["damage_photo", "order_id"],
        "autonomy_tier": "hold",
        "escalate_if": "CV confidence < 0.6 OR image does not match ordered SKU",
    },
    "won't turn on": {
        "policy_rule": "hardware_fault_v1",
        "confidence_threshold": 0.70,
        "fraud_gate": False,
        "nqe_required_fields": ["order_id", "purchase_date"],
        "autonomy_tier": "hold",
        "escalate_if": "outside warranty period",
    },
    "file a complaint": {
        "policy_rule": "complaint_intake_v1",
        "confidence_threshold": 0.75,
        "fraud_gate": True,
        "nqe_required_fields": ["order_id", "description"],
        "autonomy_tier": "auto",
        "escalate_if": "fraud_score > 70 OR repeat complaint for same SKU",
    },
    "request under review": {
        "policy_rule": "human_review_policy_v1",
        "confidence_threshold": 0.60,
        "fraud_gate": False,
        "nqe_required_fields": [],
        "autonomy_tier": "hold",
        "escalate_if": "SLA breach > 4h",
    },
    "chat with a human": {
        "policy_rule": "human_escalation_v1",
        "confidence_threshold": 0.50,
        "fraud_gate": False,
        "nqe_required_fields": [],
        "autonomy_tier": "escalate",
        "escalate_if": "user requests human agent explicitly",
    },
    "report fraud": {
        "policy_rule": "fraud_report_v1",
        "confidence_threshold": 0.50,
        "fraud_gate": False,
        "nqe_required_fields": ["description"],
        "autonomy_tier": "escalate",
        "escalate_if": "always escalates to security team",
    },
    "account locked": {
        "policy_rule": "account_security_v1",
        "confidence_threshold": 0.60,
        "fraud_gate": False,
        "nqe_required_fields": ["account_email"],
        "autonomy_tier": "hold",
        "escalate_if": "suspicious activity detected OR repeated lock events",
    },
    "blue screen": {
        "policy_rule": "hardware_fault_v1",
        "confidence_threshold": 0.70,
        "fraud_gate": False,
        "nqe_required_fields": ["stop_code", "order_id"],
        "autonomy_tier": "auto",
        "escalate_if": "hardware diagnostic required OR outside warranty period",
    },
    "bsod": {
        "policy_rule": "hardware_fault_v1",
        "confidence_threshold": 0.70,
        "fraud_gate": False,
        "nqe_required_fields": ["stop_code", "order_id"],
        "autonomy_tier": "auto",
        "escalate_if": "hardware diagnostic required",
    },
}


def _apply_policy_overlay(bank: List[Dict]) -> List[Dict]:
    """Inject policy metadata into FAQ entries via substring match on the question."""
    for entry in bank:
        q_lower = str(entry.get("q") or "").lower()
        for q_fragment, policy in _FAQ_POLICY_OVERLAY.items():
            if q_fragment in q_lower:
                for k, v in policy.items():
                    entry.setdefault(k, v)
                break
    return bank


FAQ_BANK = _apply_policy_overlay(FAQ_BANK)


def _tokenize(text: str) -> List[str]:
    tokens = [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]
    return [t for t in tokens if t not in _FAQ_STOPWORDS]


def match_faq(query: str) -> Tuple[Dict[str, object] | None, float]:
    tokens = set(_tokenize(query))
    best = None
    best_score = 0.0
    for item in FAQ_BANK:
        tags = set(item.get("tags") or [])
        q_tokens = set(_tokenize(str(item.get("q") or "")))
        overlap = len(tokens & tags) + len(tokens & q_tokens)
        if overlap > best_score:
            best = item
            best_score = float(overlap)
    return best, best_score


def export_policy_rules_json() -> Dict:
    """Return a policy-rules dict keyed by FAQ question, suitable for orchestrator loading."""
    rules = {}
    for entry in FAQ_BANK:
        if "policy_rule" in entry:
            rules[str(entry["q"])] = {
                "policy_rule": entry.get("policy_rule"),
                "confidence_threshold": entry.get("confidence_threshold"),
                "fraud_gate": entry.get("fraud_gate"),
                "nqe_required_fields": entry.get("nqe_required_fields"),
                "autonomy_tier": entry.get("autonomy_tier"),
                "escalate_if": entry.get("escalate_if"),
            }
    return rules
