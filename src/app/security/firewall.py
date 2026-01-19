from dataclasses import dataclass
from typing import Dict, Tuple


HARD_CAP_DISCOUNT_PERCENT = 30
AUTO_APPROVE_THRESHOLD_CENTS = 25000  # $250
MAX_HOURLY_DISCOUNTS_CENTS = 500000   # $5,000


@dataclass
class FirewallDecision:
    allowed: bool
    approval_required: bool
    reason: str


class TransactionFirewall:
    def __init__(self, flags: Dict):
        self.flags = flags

    def check_pricing(self, cart_total_cents: int, proposed_discount_percent: int) -> FirewallDecision:
        if proposed_discount_percent > HARD_CAP_DISCOUNT_PERCENT:
            return FirewallDecision(False, True, "Discount exceeds hard cap")

        discounted = int(cart_total_cents * (100 - proposed_discount_percent) / 100)
        if discounted >= AUTO_APPROVE_THRESHOLD_CENTS:
            return FirewallDecision(True, True, ">= $250 requires human approval")

        return FirewallDecision(True, False, "Within auto-approve limits")

    def idempotency_ok(self, key_exists: bool) -> Tuple[bool, str]:
        if key_exists:
            return False, "Duplicate execution (idempotency key exists)"
        return True, "OK"
