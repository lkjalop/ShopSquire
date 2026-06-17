"""Answer composer — single owner of the buyer-facing message (strangler step, 2026-06).

WHY: in recommend.py the assistant_message is assigned at ~6 scattered sites, so a
security note, a knowledge answer, a budget verdict and a product summary can't easily
coexist — whichever site runs last wins, and compound queries ("what's the difference
between SSD and HDD, and which laptop under 1200 has a good one?") answer only one part.

This module assembles the final message from NAMED SECTIONS in a fixed order. It is the
consumer of query_decomposer's sub_questions (Phase B) and the home for the security
"challenge" — both become sections instead of scattered hacks.

Pure functions, no I/O, no LLM. The LLM-dependent section TEXT is produced by the caller
(recommend.py reuses _build_knowledge_answer etc.) and passed in; this module only orders,
de-duplicates and joins. Never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

# Fixed render order. Security leads (the buyer must see the warning first); the product
# summary trails; a recovery line only appears when there is no product summary.
_SECTION_ORDER = ["security", "knowledge", "budget", "product", "recovery"]
_ORDER_INDEX = {k: i for i, k in enumerate(_SECTION_ORDER)}


@dataclass
class AnswerSection:
    kind: str
    text: str

    def clean(self) -> str:
        return re.sub(r"\s+", " ", str(self.text or "")).strip()


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(s or "").lower()).strip()


def _is_subsumed(candidate: str, existing: List[str]) -> bool:
    """True if `candidate` is already (nearly) contained in an existing section — avoids
    saying the budget verdict twice when the product summary already states it."""
    c = _normalize(candidate)
    if not c:
        return True
    for e in existing:
        en = _normalize(e)
        if not en:
            continue
        if c in en or en in c:
            return True
        # high token overlap → treat as duplicate
        ct, et = set(c.split()), set(en.split())
        if ct and len(ct & et) / len(ct) >= 0.85:
            return True
    return False


def compose_answer(sections: List[AnswerSection]) -> str:
    """Order, de-duplicate and join sections into one coherent message. A `recovery`
    section is dropped when a `product` section is present (don't say 'no match' then
    list matches). Returns '' only when every section is empty."""
    try:
        present = {}
        for s in sections or []:
            if not isinstance(s, AnswerSection):
                continue
            txt = s.clean()
            if txt and s.kind in _ORDER_INDEX:
                # last non-empty wins per kind
                present[s.kind] = txt
        if "product" in present:
            present.pop("recovery", None)
        ordered_kinds = sorted(present.keys(), key=lambda k: _ORDER_INDEX[k])
        out: List[str] = []
        for k in ordered_kinds:
            txt = present[k]
            if _is_subsumed(txt, out):
                continue
            # ensure each section ends as its own sentence
            if txt and txt[-1] not in ".!?…":
                txt = txt + "."
            out.append(txt)
        return " ".join(out).strip()
    except Exception:
        # Fail safe: return the first non-empty section text we can find.
        for s in sections or []:
            try:
                t = s.clean()
                if t:
                    return t
            except Exception:
                continue
        return ""


def needs_composition(plan: object) -> bool:
    """True when a plan is compound AND mixes a conceptual ask (knowledge/comparison or
    a budget question) with a product/other ask — i.e. a single answer would drop a part.
    Pure check on the decomposer's output; safe on any object."""
    try:
        if not getattr(plan, "is_compound", False):
            return False
        subs = list(getattr(plan, "sub_questions", []) or [])
        if len(subs) < 2:
            return False
        kinds = set()
        for sq in subs:
            if getattr(sq, "answer_without_products", False) or getattr(sq, "is_budget_question", False):
                kinds.add("conceptual")
            if str(getattr(sq, "intent", "")) in ("product_search", "recommendation_multi"):
                kinds.add("product")
        # conceptual + (product or a second conceptual of different shape) → compose
        return "conceptual" in kinds and len(subs) >= 2
    except Exception:
        return False


# ── Security challenge (Thread 3) ─────────────────────────────────────────────
# Map a detected image-security signal to an EDUCATIONAL, category-specific challenge
# the buyer actually understands — naming the RISK CATEGORY and the action taken, but
# NEVER echoing the payload (a decoded malicious URL/instruction is itself a delivery
# vector). Severity-ranked: the most serious present signal wins. The signal→category
# mapping is the mechanism; the wording is flavour.
_SECURITY_CHALLENGES = [
    ("steg_suspicious",
     "Heads up: the uploaded image shows signs of hidden embedded data (steganography) — "
     "a technique used to smuggle instructions or beacons inside an ordinary-looking photo. "
     "I've isolated it for security review and used only safe, visible features."),
    ("c2_beacon",
     "Heads up: the uploaded image matched a command-and-control beacon pattern. I've "
     "quarantined it for detonation analysis and ignored its contents entirely."),
    ("qr_prompt_injection",
     "Heads up: the uploaded image contains a QR code with embedded instructions — unusual "
     "for a product photo and a common phishing/injection vector. I've quarantined it and "
     "ignored what it points to."),
    ("qr_quarantined",
     "Heads up: I found a QR code in the uploaded image. That's unusual for a product photo, "
     "so I've quarantined it and based recommendations only on the visible product."),
    ("ocr_prompt_injection",
     "Heads up: the uploaded image contains text that reads like an instruction to me rather "
     "than a product label. I've treated it as a potential prompt-injection and ignored it."),
    ("manipulation_detected",
     "Heads up: the uploaded image appears digitally manipulated to fool image recognition. "
     "I've flagged it and relied on your typed request instead."),
    ("adversarial",
     "Heads up: the uploaded image looks adversarially perturbed (engineered to mislead vision "
     "models). I've flagged it and used your text request instead."),
    ("pii_detected",
     "Heads up: the uploaded image appears to contain personal or sensitive information. I've "
     "redacted it from processing and won't store it."),
]


def security_challenge(signals: Optional[Dict[str, object]]) -> Optional[str]:
    """Return one educational buyer-facing security challenge for the highest-severity
    signal present, or a generic one if flagged without a specific signal, or None."""
    try:
        sig = signals or {}
        def _on(k: str) -> bool:
            v = sig.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v) >= 0.5  # e.g. adversarial_score
            return bool(v)
        # adversarial can arrive as a score field
        if _on("adversarial_score"):
            sig = {**sig, "adversarial": True}
        for key, text in _SECURITY_CHALLENGES:
            if _on(key):
                return text
        if str(sig.get("trust_state") or "").lower() == "under_review" or _on("image_flagged"):
            return ("Heads up: the uploaded image is under security review, so I've based "
                    "recommendations on sanitized hints only.")
        return None
    except Exception:
        return None


def conceptual_sub_questions(plan: object) -> List[str]:
    """The sub-question texts that want a conceptual (non-product) answer — these are
    what the caller should answer with the knowledge/comparison helper and pass back."""
    out: List[str] = []
    try:
        for sq in list(getattr(plan, "sub_questions", []) or []):
            if getattr(sq, "answer_without_products", False) or getattr(sq, "is_budget_question", False):
                t = str(getattr(sq, "text", "") or "").strip()
                if t:
                    out.append(t)
    except Exception:
        pass
    return out
