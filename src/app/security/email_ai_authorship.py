"""AI-authored / synthetic-text heuristic (agnostic CORE) — a stylometry signal DISTINCT from the
intent-similarity BEC scorer. It answers "does this read like machine-generated prose?", which
matters because modern phishing/BEC is increasingly LLM-drafted: fluent, uniform, over-polished.

Deterministic + dependency-free (no model call): burstiness (sentence-length variance), formal-
transition density, contraction scarcity, and lexical-repetition flatness — the stylometric tells
of generated text. Returns a bounded [0,1] score + reasons. This is a WEAK signal on its own (lots
of legitimate mail is templated/formal), so it ships SHADOW-first: computed and logged, gated OFF
from the verdict until calibrated (EMAIL_AI_TEXT_ENFORCED). Vertical-blind — pure text statistics.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List

# Formal discourse markers over-represented in generated prose.
_FORMAL_TRANSITIONS = (
    "furthermore", "moreover", "additionally", "consequently", "nevertheless", "nonetheless",
    "in conclusion", "in summary", "it is important to note", "please be advised", "as such",
    "in order to", "with regard to", "we would like to", "kindly note", "rest assured",
)
_CONTRACTION_RE = re.compile(r"\b\w+'(?:s|re|ve|ll|d|t|m)\b", re.I)
_SENT_SPLIT_RE = re.compile(r"[.!?]+(?:\s+|$)")
_WORD_RE = re.compile(r"[A-Za-z']+")


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]


def score_ai_authorship(text: str) -> Dict[str, Any]:
    """Heuristic probability that ``text`` is machine-generated. Returns
    {score:0..1, reasons:[...], metrics:{...}, detected:bool}. Never raises."""
    t = str(text or "").strip()
    words = _WORD_RE.findall(t.lower())
    sents = _sentences(t)
    metrics: Dict[str, Any] = {"words": len(words), "sentences": len(sents)}
    reasons: List[str] = []
    # Too short to judge — do not guess.
    if len(words) < 40 or len(sents) < 3:
        return {"score": 0.0, "reasons": ["insufficient_length"], "metrics": metrics, "detected": False}

    score = 0.0

    # 1) Low burstiness: human writing varies sentence length; generated text is uniform.
    lengths = [len(_WORD_RE.findall(s)) for s in sents]
    mean_len = sum(lengths) / max(1, len(lengths))
    var = sum((n - mean_len) ** 2 for n in lengths) / max(1, len(lengths))
    cv = (math.sqrt(var) / mean_len) if mean_len > 0 else 0.0
    metrics["sentence_len_cv"] = round(cv, 3)
    if cv < 0.35:
        score += 0.30
        reasons.append("uniform_sentence_length")

    # 2) Formal-transition density.
    tl = t.lower()
    transition_hits = sum(tl.count(p) for p in _FORMAL_TRANSITIONS)
    density = transition_hits / max(1, len(sents))
    metrics["transition_density"] = round(density, 3)
    if density >= 0.5:
        score += 0.30
        reasons.append("high_formal_transition_density")
    elif density >= 0.25:
        score += 0.15
        reasons.append("elevated_formal_transitions")

    # 3) Contraction scarcity: generated business prose rarely contracts.
    contractions = len(_CONTRACTION_RE.findall(t))
    contraction_rate = contractions / max(1, len(words))
    metrics["contraction_rate"] = round(contraction_rate, 4)
    if contraction_rate == 0.0 and len(words) >= 60:
        score += 0.20
        reasons.append("no_contractions")

    # 4) Lexical repetition flatness: generated text under-repeats content words (high type/token).
    unique_ratio = len(set(words)) / max(1, len(words))
    metrics["type_token_ratio"] = round(unique_ratio, 3)
    if unique_ratio >= 0.72:
        score += 0.20
        reasons.append("high_lexical_diversity")

    score = max(0.0, min(1.0, score))
    return {"score": round(score, 3), "reasons": reasons, "metrics": metrics, "detected": score >= 0.6}
