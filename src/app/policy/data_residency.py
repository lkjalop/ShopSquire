"""CRIT-10 — Data residency and cross-border transfer gate.

Enforces transfer-mechanism documentation before personal data (PII)
leaves the Australian data boundary toward external LLM providers or
third-party APIs.

Framework alignment
-------------------
* Australian Privacy Act 1988, APP 8.1 — cross-border disclosure
  The entity must take reasonable steps to ensure overseas recipients
  handle data in accordance with the APPs, or otherwise hold the
  originating entity accountable.

* GDPR Art 44–49 — transfers to third countries
  Requires an adequacy decision, SCCs, BCRs, or explicit consent.

* ISO 27001 A.5.33 — protection of records (residency constraints)

* NIST SP 800-53 SA-9 — external system services

Usage
-----
Before sending any prompt that may contain PII to an external provider::

    from src.app.policy.data_residency import check_transfer, TransferMechanism

    verdict = check_transfer("openai")
    if not verdict.allowed:
        raise RuntimeError(f"Data residency block: {verdict.notes}")
    # Optional: log the transfer for RoPA
    log_transfer(provider="openai", verdict=verdict, data_categories=["order_context"])

Maintenance
-----------
* When a new external provider is added, register it here BEFORE wiring it
  into the LLM provider selection logic.
* When a DPA is signed, update ``signed_dpa`` and ``dpa_date`` fields.
* Review annually or when a provider changes their data processing terms.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transfer mechanisms (GDPR Art 46 / APP 8)
# ---------------------------------------------------------------------------

class TransferMechanism(str, Enum):
    SCCs                   = "standard_contractual_clauses"
    BINDING_CORPORATE_RULES = "binding_corporate_rules"
    ADEQUACY_DECISION      = "adequacy_decision"
    EXPLICIT_CONSENT       = "explicit_consent"
    ON_PREMISE             = "on_premise_no_transfer"
    BLOCKED                = "blocked"


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

@dataclass
class ResidencyVerdict:
    provider:           str
    allowed:            bool
    mechanism:          TransferMechanism
    destination_country: str
    signed_dpa:         bool                = False
    dpa_date:           Optional[str]       = None   # ISO 8601
    data_categories:    List[str]           = field(default_factory=list)
    notes:              str                 = ""

    def assert_allowed(self) -> None:
        """Raise RuntimeError if the transfer is not permitted."""
        if not self.allowed:
            raise RuntimeError(
                f"Data residency BLOCK for provider '{self.provider}': {self.notes}"
            )


# ---------------------------------------------------------------------------
# Approved provider registry
# ---------------------------------------------------------------------------
# Each entry documents the legal basis for transferring data to that provider.
# Update this table when DPAs are signed or providers change their terms.
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, ResidencyVerdict] = {
    # On-premise Ollama — no data leaves AU, no transfer required
    "ollama": ResidencyVerdict(
        provider="ollama",
        allowed=True,
        mechanism=TransferMechanism.ON_PREMISE,
        destination_country="AU",
        signed_dpa=False,
        notes="Fully on-premise — no data transfer occurs",
    ),
    "ollama_local": ResidencyVerdict(
        provider="ollama_local",
        allowed=True,
        mechanism=TransferMechanism.ON_PREMISE,
        destination_country="AU",
        signed_dpa=False,
        notes="Fully on-premise — no data transfer occurs",
    ),
    # OpenAI — SCCs documented; DPA to be signed before production PII use
    "openai": ResidencyVerdict(
        provider="openai",
        allowed=True,
        mechanism=TransferMechanism.SCCs,
        destination_country="US",
        signed_dpa=False,                  # TODO: execute DPA before prod PII
        dpa_date=None,
        notes=(
            "OpenAI EU/AU SCCs applicable. "
            "DPA must be executed before sending real customer PII. "
            "See: https://openai.com/policies/data-processing-addendum"
        ),
    ),
    # Anthropic — SCCs documented; DPA to be signed before production PII use
    "anthropic": ResidencyVerdict(
        provider="anthropic",
        allowed=True,
        mechanism=TransferMechanism.SCCs,
        destination_country="US",
        signed_dpa=False,
        dpa_date=None,
        notes=(
            "Anthropic DPA + SCCs. "
            "DPA must be executed before sending real customer PII. "
            "See: https://www.anthropic.com/legal/data-processing-addendum"
        ),
    ),
    # Google Gemini / VertexAI — adequacy + SCCs via GCP DPA
    "gemini": ResidencyVerdict(
        provider="gemini",
        allowed=True,
        mechanism=TransferMechanism.SCCs,
        destination_country="US",
        signed_dpa=False,
        dpa_date=None,
        notes="Google Cloud DPA covers Vertex AI / Gemini API endpoints.",
    ),
    # Groq — no DPA documented yet — blocked for PII-containing prompts
    "groq": ResidencyVerdict(
        provider="groq",
        allowed=False,
        mechanism=TransferMechanism.BLOCKED,
        destination_country="US",
        signed_dpa=False,
        notes="Groq DPA not yet executed. Do not send PII until DPA is signed.",
    ),
    # Mistral AI — EU-based, GDPR adequacy applies for AU under equivalence
    "mistral": ResidencyVerdict(
        provider="mistral",
        allowed=True,
        mechanism=TransferMechanism.ADEQUACY_DECISION,
        destination_country="FR",
        signed_dpa=False,
        notes="Mistral AI is EU-based; GDPR framework applies.",
    ),
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_transfer(
    provider_key: str,
    data_categories: Optional[List[str]] = None,
) -> ResidencyVerdict:
    """Return the ResidencyVerdict for the given provider.

    Parameters
    ----------
    provider_key:     The provider identifier (e.g. "openai", "ollama").
                      Case-insensitive.
    data_categories:  Optional list of PII categories being transferred
                      (e.g. ["name", "email", "order_history"]).
                      Stored on the verdict for audit logging.

    Returns
    -------
    ResidencyVerdict — callers should call ``verdict.assert_allowed()``
    or check ``verdict.allowed`` before sending data.
    """
    key = (provider_key or "").strip().lower()
    verdict = _REGISTRY.get(key)

    if verdict is None:
        logger.warning(
            "data_residency unknown_provider provider=%s — BLOCKING by default", key
        )
        return ResidencyVerdict(
            provider=key,
            allowed=False,
            mechanism=TransferMechanism.BLOCKED,
            destination_country="unknown",
            notes=(
                f"Provider '{key}' is not in the approved transfer registry. "
                "Add a ResidencyVerdict entry in policy/data_residency.py before use."
            ),
        )

    # Attach data categories to a copy so we don't mutate the registry entry
    import copy
    v = copy.copy(verdict)
    v.data_categories = list(data_categories or [])

    # DPA ENFORCEMENT (P1-2): signed_dpa was previously only LOGGED, never enforced — so PII could be
    # transferred to a cloud provider (openai/anthropic) with an UNSIGNED DPA. A cross-border transfer
    # that carries declared PII now requires a signed DPA; fail CLOSED (block) until it is executed.
    # On-premise providers (ollama_local/local) transfer nothing, so they are exempt. NOTE: this gates
    # on DECLARED data_categories — a caller that sends PII without declaring it still needs to pass
    # categories for the gate to fire (the transfer contract).
    _cross_border = v.mechanism not in (TransferMechanism.ON_PREMISE, TransferMechanism.BLOCKED)
    if v.allowed and _cross_border and v.data_categories and not v.signed_dpa:
        v.allowed = False
        v.notes = (f"BLOCKED (P1-2): PII transfer to '{key}' requires a signed DPA before production "
                   f"use (categories={v.data_categories}). Execute the DPA, then set "
                   f"signed_dpa=True + dpa_date on the provider's ResidencyVerdict.")
        logger.warning("data_residency PII_transfer_blocked_no_dpa provider=%s categories=%s mechanism=%s",
                       key, v.data_categories, v.mechanism)

    if not v.allowed:
        logger.warning(
            "data_residency transfer_blocked provider=%s mechanism=%s notes=%s",
            key, v.mechanism, v.notes,
        )
    else:
        logger.debug(
            "data_residency transfer_allowed provider=%s country=%s mechanism=%s signed_dpa=%s",
            key, v.destination_country, v.mechanism, v.signed_dpa,
        )

    return v


def register_provider(verdict: ResidencyVerdict) -> None:
    """Register or update a provider entry at runtime (e.g. from config)."""
    _REGISTRY[verdict.provider.lower()] = verdict


def list_providers() -> Dict[str, ResidencyVerdict]:
    """Return all registered providers and their transfer status."""
    return dict(_REGISTRY)
