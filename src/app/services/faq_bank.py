from __future__ import annotations

import re
from typing import Dict, List, Tuple


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
]


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


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
