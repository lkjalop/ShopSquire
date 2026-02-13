from dataclasses import dataclass
from typing import Dict, Tuple, Optional


HARD_CAP_DISCOUNT_PERCENT = 30
AUTO_APPROVE_THRESHOLD_CENTS = 25000  # $250
MAX_HOURLY_DISCOUNTS_CENTS = 500000   # $5,000


@dataclass
class FirewallDecision:
    allowed: bool
    approval_required: bool
    reason: str
    escalation_role: Optional[str] = None
    policy_version: Optional[str] = None


class TransactionFirewall:
    def __init__(self, flags: Dict):
        self.flags = flags

    def check_pricing(self, cart_total_cents: int, proposed_discount_percent: int, actor_context: Optional[Dict] = None) -> FirewallDecision:
        if cart_total_cents <= 0:
            return FirewallDecision(False, True, "Cart total invalid", escalation_role=self.flags.get("ESCALATION_ROLE_MERCHANT", "merchant"), policy_version=self.flags.get("POLICY_VERSION", "v1"))
        if proposed_discount_percent < 0 or proposed_discount_percent > 100:
            return FirewallDecision(False, True, "Discount percent invalid", escalation_role=self.flags.get("ESCALATION_ROLE_OWNER", "owner"), policy_version=self.flags.get("POLICY_VERSION", "v1"))
        if proposed_discount_percent > HARD_CAP_DISCOUNT_PERCENT:
            return FirewallDecision(False, True, "Discount exceeds hard cap", escalation_role="owner", policy_version=self.flags.get("POLICY_VERSION", "v1"))

        discounted = int(cart_total_cents * (100 - proposed_discount_percent) / 100)
        if cart_total_cents >= MAX_HOURLY_DISCOUNTS_CENTS:
            return FirewallDecision(True, True, "High cart total requires human approval", escalation_role=self.flags.get("ESCALATION_ROLE_OWNER", "owner"), policy_version=self.flags.get("POLICY_VERSION", "v1"))
        # If the final price still leaves merchant exposure above threshold,
        # require escalating approval depending on amount.
        if discounted >= AUTO_APPROVE_THRESHOLD_CENTS:
            # Escalation: owner approval required for amounts >= AUTO_APPROVE_THRESHOLD_CENTS.
            role = "owner"
            # If flags define an org-level security approver, prefer that
            role = self.flags.get("ESCALATION_ROLE_OWNER", role)
            return FirewallDecision(True, True, ">= $250 requires human approval", escalation_role=role, policy_version=self.flags.get("POLICY_VERSION", "v1"))

        # Soft checks: if proposed discount is near cap, require merchant review
        if proposed_discount_percent >= (HARD_CAP_DISCOUNT_PERCENT - 5):
            return FirewallDecision(True, True, "High discount near hard cap; merchant approval recommended", escalation_role=self.flags.get("ESCALATION_ROLE_MERCHANT", "merchant"), policy_version=self.flags.get("POLICY_VERSION", "v1"))

        return FirewallDecision(True, False, "Within auto-approve limits", escalation_role=None, policy_version=self.flags.get("POLICY_VERSION", "v1"))

    def idempotency_ok(self, key_exists: bool) -> Tuple[bool, str]:
        if key_exists:
            return False, "Duplicate execution (idempotency key exists)"
        return True, "OK"
