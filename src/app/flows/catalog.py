from __future__ import annotations

from typing import Dict, List, Optional

from src.app.flows.nqe_templates import TemplateStore


class QuestionTemplateCatalog:
    def __init__(self) -> None:
        self._store = TemplateStore()
        self._templates: Dict[str, Dict[str, List[dict]]] = {
            "product_search": {
                "general": [
                    {
                        "id": "ask_budget",
                        "text": "What budget range should I use for this search?",
                        "goal": "clarify_details",
                        "evidence_needed": ["none"],
                    },
                    {
                        "id": "ask_budget_tier",
                        "text": "Do you have a price tier in mind (Under $1000, $1000–$1500, $1500+)?",
                        "goal": "clarify_details",
                        "evidence_needed": ["none"],
                    },
                    {
                        "id": "ask_specs",
                        "text": "Any must-have specs (RAM, storage, screen size, OS)?",
                        "goal": "clarify_details",
                        "evidence_needed": ["none"],
                    },
                    {
                        "id": "ask_use_case",
                        "text": "What will you primarily use it for (work, gaming, travel, creative)?",
                        "goal": "clarify_details",
                        "evidence_needed": ["none"],
                    },
                    {
                        "id": "ask_platform",
                        "text": "Do you prefer a platform (Windows, macOS, Linux)?",
                        "goal": "clarify_details",
                        "evidence_needed": ["none"],
                    },
                    {
                        "id": "ask_brand_pref",
                        "text": "Any brand preference (Apple, Dell, Lenovo, ASUS, etc.)?",
                        "goal": "clarify_details",
                        "evidence_needed": ["none"],
                    },
                ]
            },
            "refund_request": {
                "general": [
                    {
                        "id": "refund_reason",
                        "text": "Can you briefly describe what went wrong with the item?",
                        "goal": "clarify_details",
                        "evidence_needed": ["none"],
                    },
                    {
                        "id": "refund_evidence",
                        "text": "Please upload a photo of the item and the packaging label.",
                        "goal": "verify_defect",
                        "evidence_needed": ["photo"],
                    },
                ],
                "laptop": [
                    {
                        "id": "serial_photo",
                        "text": "Could you share a photo of the serial label on the laptop?",
                        "goal": "verify_eligibility",
                        "evidence_needed": ["photo", "serial"],
                    }
                ],
            },
            "shipment_verification": {
                "general": [
                    {
                        "id": "ship_address_confirm",
                        "text": "Can you confirm the delivery address used at checkout?",
                        "goal": "clarify_details",
                        "evidence_needed": ["none"],
                    },
                    {
                        "id": "tracking_number",
                        "text": "If you have it, please share the tracking number.",
                        "goal": "verify_eligibility",
                        "evidence_needed": ["none"],
                    },
                ]
            },
            "fraud_alert": {
                "general": [
                    {
                        "id": "fraud_details",
                        "text": "What makes you believe the product is fraudulent or counterfeit?",
                        "goal": "clarify_details",
                        "evidence_needed": ["none"],
                    },
                    {
                        "id": "fraud_evidence",
                        "text": "Please upload photos of the product and any included documentation.",
                        "goal": "verify_defect",
                        "evidence_needed": ["photo"],
                    },
                ]
            },
        }

    def get_templates(
        self,
        intent: str,
        category: str,
        tenant_id: Optional[str] = None,
        *,
        variant: Optional[str] = None,
        version: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> List[dict]:
        # `tenant_id` reserved for tenant-scoped template overrides.
        # Prefer external template store for versioned tenant overrides.
        try:
            ext = self._store.get_templates(
                intent=intent,
                product_category=category,
                tenant_id=tenant_id,
                variant=variant,
                version=version,
                trace_id=trace_id,
            )
            if ext:
                return ext
        except Exception:
            pass
        # Fallback to deterministic in-code defaults.
        bucket = self._templates.get(intent, {})
        return bucket.get(category, []) + bucket.get("general", [])
