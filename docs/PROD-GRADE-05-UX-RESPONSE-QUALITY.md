# Production-Grade: UX / Response Quality
*Eliminating Robotic Text, Raw JSON, and Technical Leakage | 2026-03-25*

---

## The Problem: Three Layers of Robotic Text

### Layer 1 — LLM Response Is Generic / Doesn't Answer the Question

From `sec-LLM-summ.png`: User asks "Is $1800 enough for gaming?" → response says "I found 3 matches between $800–$1800" instead of "Yes, $1800 is enough."

**Root cause (`recommend.py` ~line 2865–2930):** The prompt has been partially fixed (BUG-6 fix is in the code per exploration), but the fix only applies to the `_summarize_results()` path. The `_build_brand_budget_answer()` path and the fallback paths still produce mechanical templated text.

### Layer 2 — Agent Trace Leaks JSON to the UI

The SSE stream emits events like:
```json
{"thinking": {"trace_id": "abc-123", "ts": 1234567890}}
{"retrieval": {"agents": ["NLP_Search_Agent", "Candidate_Retrieval_Agent"], "ts": ...}}
{"answer": {"proposal": {...raw JSON...}, "ranked_skus": ["SKU-001", "SKU-002"]}}
```

These are consumed by the frontend. If the frontend doesn't render them correctly, raw `{"ranked_skus": [...]}` appears in the chat bubble.

### Layer 3 — Security / Forensics Output Is Technical Jargon

Agent steps like:
```
ELA_splice_score: 0.847
copy_move_detected: True
phash_distance: 12
forensics_confidence: 0.72
```

...are meaningless to a merchant or customer service rep.

---

## Architecture: ResponseNormalizer

```
CURRENT:
  agent output → SSE event → frontend renders raw JSON
  LLM text → recommend.py → SSE "answer" → chat bubble
  forensics → trace panel → technical fields shown

PRODUCTION:
  agent output → SSE event → ResponseNormalizer → plain English
  LLM text → recommend.py → ResponseNormalizer.polish() → chat bubble
  forensics → ResponseNormalizer.forensics_to_english() → "This image appears genuine"
  trace panel → structured but human-readable labels
```

---

## Step 1 — Create ResponseNormalizer Service

**New file:** `src/app/services/response_normalizer.py`

```python
# src/app/services/response_normalizer.py
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional


class ResponseNormalizer:
    """
    Translates agent outputs, forensics results, and LLM text into
    plain business English. All methods are pure functions — no I/O.
    """

    # ── LLM text polish ────────────────────────────────────────────────────────
    @staticmethod
    def polish_llm_text(text: str, query: str = "") -> str:
        """
        Light post-processing to make LLM output less robotic.
        Does NOT change the content — only smooths delivery.
        """
        if not text:
            return text

        # Remove stray JSON/dict artifacts that leaked from prompt context
        text = re.sub(r'\{["\'][\w_]+["\']:\s*[^}]{0,200}\}', '', text)

        # Remove leading "Based on the information provided" and similar preambles
        preambles = [
            r'^Based on (the |your |)information (provided|available)[,.]?\s*',
            r'^According to (the |)search results[,.]?\s*',
            r'^Here (is|are) (the |)results?[.:]?\s*',
            r'^I (found|located|retrieved|identified) \d+ (result|match|product)s?\.',
            r'^The search returned \d+ (result|match|product)s?\.',
        ]
        for pattern in preambles:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()

        # Normalise excessive product listing (3 products → short list, not bullet wall)
        text = re.sub(r'\n\s*[-•]\s*', '\n• ', text)  # consistent bullets

        return text.strip()

    # ── Forensics / security output ────────────────────────────────────────────
    @staticmethod
    def forensics_to_english(forensics_result: Dict[str, Any]) -> str:
        """
        Convert ForensicsResult fields to a plain-English verdict.
        Input: dict from ImageForensicsService.analyze()
        """
        score = forensics_result.get("manipulation_score", 0)
        splice = forensics_result.get("splice_score", 0)
        copy_move = forensics_result.get("copy_move_score", 0)
        metadata_flags = forensics_result.get("metadata_flags", [])
        blur = forensics_result.get("blur_score", 0)

        if score >= 0.8 or splice >= 0.7:
            concern = "high"
        elif score >= 0.5 or copy_move >= 0.5:
            concern = "moderate"
        elif score >= 0.2:
            concern = "low"
        else:
            concern = "none"

        if concern == "none":
            return "This image appears genuine — no manipulation signals detected."
        if concern == "low":
            return "This image has minor inconsistencies that may indicate compression artefacts. No strong evidence of manipulation."
        if concern == "moderate":
            parts = []
            if copy_move >= 0.5:
                parts.append("areas of the image appear to have been copied and pasted")
            if splice >= 0.4:
                parts.append("portions of the image may have been spliced together")
            if metadata_flags:
                parts.append("metadata inconsistencies were found")
            desc = "; ".join(parts) if parts else "anomalies were detected"
            return f"This image has been flagged for review — {desc}. Recommend manual verification."
        # high
        return (
            "This image shows strong indicators of manipulation. "
            "It should not be accepted as authentic evidence for a claim or return."
        )

    @staticmethod
    def fraud_score_to_english(risk_level: str, score: float, signals: Dict[str, bool]) -> str:
        """Convert fraud score + signals to a merchant-readable summary."""
        active = [k.replace("_", " ") for k, v in signals.items() if v]
        if risk_level == "minimal":
            return "No fraud signals detected — this transaction looks normal."
        if risk_level == "low":
            return f"Low fraud risk ({score:.0%}). Minor signals present: {', '.join(active[:2]) if active else 'none'}."
        if risk_level == "medium":
            top = ", ".join(active[:3]) if active else "multiple risk factors"
            return f"Medium fraud risk ({score:.0%}). Flagged signals: {top}. Consider additional verification."
        # high
        top = ", ".join(active[:4]) if active else "multiple critical factors"
        return (
            f"High fraud risk ({score:.0%}). Triggered: {top}. "
            f"This transaction should be held for manual review before processing."
        )

    @staticmethod
    def anomaly_to_english(anomalies: List[Dict[str, Any]]) -> str:
        """Convert anomaly detector output to a plain summary."""
        if not anomalies:
            return ""
        critical = [a for a in anomalies if a.get("severity") in ("critical", "high")]
        if critical:
            items = "; ".join(a.get("plain_english", a.get("domain", "")) for a in critical[:3])
            return f"Unusual activity detected: {items}"
        items = "; ".join(a.get("plain_english", a.get("domain", "")) for a in anomalies[:2])
        return f"Minor anomalies observed: {items}"

    @staticmethod
    def agent_steps_to_english(steps: List[Dict[str, Any]]) -> List[str]:
        """
        Convert raw agent step dicts (from orchestrator trace) to
        human-readable bullet points for the decision trace panel.
        """
        labels = {
            "NLP_Search_Agent":         "Understood your query",
            "Candidate_Retrieval_Agent":"Searched the product catalog",
            "Product_Ranking_Agent":    "Ranked results by relevance",
            "Fraud_Scoring_Agent":      "Checked for fraud signals",
            "CV_Label_Agent":           "Analysed uploaded image",
            "Inventory_Agent":          "Checked stock availability",
            "NQE":                      "Prepared follow-up questions",
            "Policy_Gate_Agent":        "Applied merchant policies",
            "Security_Observer_Agent":  "Scanned for security threats",
        }
        result = []
        for step in steps:
            agent = step.get("source_id") or step.get("agent") or "System"
            label = labels.get(agent, agent.replace("_", " "))
            payload = step.get("payload", {})
            detail = ""
            if "count" in payload:
                detail = f" — found {payload['count']} results"
            elif "score" in payload:
                score = payload["score"]
                if isinstance(score, float):
                    detail = f" — confidence {score:.0%}"
            elif "error" in payload:
                detail = f" — {payload['error']}"
            result.append(f"{label}{detail}")
        return result

    @staticmethod
    def vuln_finding_to_english(finding: Dict[str, Any]) -> str:
        """Ensure a vuln finding has a non-technical description."""
        if finding.get("plain_english"):
            return finding["plain_english"]
        cve = finding.get("cve_id", "")
        pkg = finding.get("package", "a component")
        sev = finding.get("severity", "unknown")
        fix = finding.get("fixed_version")
        base = f"Security issue in {pkg} ({cve}): rated {sev}."
        if fix:
            return f"{base} A fix is available — update to version {fix}."
        return f"{base} No patch yet — isolate or remove this component."

    @staticmethod
    def cv_triage_to_english(triage_result: Dict[str, Any]) -> str:
        """
        Convert CV triage result to a customer-service-rep readable summary.
        """
        if triage_result.get("plain_english"):
            return triage_result["plain_english"]

        severity = triage_result.get("severity", "undetermined")
        damage_type = triage_result.get("damage_type", "unknown")
        component = triage_result.get("component")

        severity_map = {
            "critical": "severe damage",
            "major":    "significant damage",
            "minor":    "minor damage",
            "undetermined": "potential damage",
            "insufficient_data": "unclear damage",
        }
        damage_map = {
            "physical":    "physical",
            "cosmetic":    "cosmetic",
            "functional":  "functional",
            "packaging":   "packaging",
            "unknown":     "",
        }
        sev_label = severity_map.get(severity, severity)
        dmg_label = damage_map.get(damage_type, "")
        comp_label = f" to the {component}" if component else ""
        return f"Image shows {dmg_label} {sev_label}{comp_label}.".replace("  ", " ").strip()
```

---

## Step 2 — Integrate ResponseNormalizer Into the SSE Stream

**File:** `src/app/routers/chat_stream.py`
**Lines:** ~51–85 (the event emission block)

```python
# chat_stream.py — import at top
from src.app.services.response_normalizer import ResponseNormalizer

# In the answer event handler (~line 75):
# BEFORE:
yield _sse_event("answer", {"proposal": proposal, "ranked_skus": ranked_skus})

# AFTER:
# Polish the assistant message before sending
if proposal.get("assistant_message"):
    proposal["assistant_message"] = ResponseNormalizer.polish_llm_text(
        proposal["assistant_message"],
        query=request_query,
    )
# Translate agent steps
if proposal.get("agent_steps"):
    proposal["agent_steps_readable"] = ResponseNormalizer.agent_steps_to_english(
        proposal["agent_steps"]
    )
yield _sse_event("answer", {"proposal": proposal, "ranked_skus": ranked_skus})
```

---

## Step 3 — Fix the Vision Router Response

**File:** `src/app/routers/vision.py`
**Find:** The endpoint that returns CV triage / forensics results

```python
# vision.py — in the triage response builder
from src.app.services.response_normalizer import ResponseNormalizer

# BEFORE (raw fields):
return {
    "damage_type": triage.damage_type,
    "severity": triage.severity,
    "confidence": triage.confidence,
    "forensics": forensics_result.__dict__,
}

# AFTER (business readable):
return {
    "summary": ResponseNormalizer.cv_triage_to_english(triage.__dict__),
    "image_verdict": ResponseNormalizer.forensics_to_english(forensics_result.__dict__),
    "severity": triage.severity,
    "confidence": round(triage.confidence, 2),
    # Raw data only in trace panel, not in chat
    "_raw": {
        "damage_type": triage.damage_type,
        "forensics_score": forensics_result.manipulation_score,
    } if settings.DEBUG else None,
}
```

---

## Step 4 — Fix the Fraud Scorer Response Surface

**File:** `src/app/services/fraud_scorer.py`
**Find:** Any method that returns the final fraud result dict

The existing `monitoring_snapshot()` returns technical field names. Add a `to_merchant_dict()` method:

```python
# fraud_scorer.py — add to FraudScore dataclass or wherever final result is built
def to_merchant_dict(self) -> Dict[str, Any]:
    """Returns a merchant-safe (non-technical) representation."""
    from src.app.services.response_normalizer import ResponseNormalizer
    return {
        "risk_level": self.risk_level,            # high / medium / low / minimal
        "summary": ResponseNormalizer.fraud_score_to_english(
            self.risk_level, self.score, self.active_signals
        ),
        "recommended_action": self._recommended_action(),
        # Only expose score, not raw signal weights
        "score": round(self.score, 2),
    }

def _recommended_action(self) -> str:
    if self.risk_level == "high":
        return "Hold for manual review before processing."
    if self.risk_level == "medium":
        return "Request additional verification (ID check or OTP)."
    if self.risk_level == "low":
        return "Process with standard monitoring."
    return "Process normally."
```

---

## Step 5 — Fix the Support / Query Router

**File:** `src/app/routers/support.py` and `src/app/routers/query.py`

Both routers likely return raw service output. Add normalizer pass:

```python
# support.py — in the FAQ resolution endpoint
from src.app.services.response_normalizer import ResponseNormalizer

# After getting FAQ result:
faq_result = await faq_service.resolve(query)

# Don't return internal similarity scores or raw IDs to the user:
return {
    "answer": faq_result.get("answer", ""),
    "category": faq_result.get("category", ""),
    # Only include similarity in trace, not in chat response
}
```

---

## Step 6 — Frontend: Render agent_steps_readable Not Raw Trace

The frontend chat component likely has a section that shows "Agent Steps." Point it to `agent_steps_readable` instead of `agent_steps`:

```typescript
// In your ChatMessage component (frontend/src/components/...)
// BEFORE:
const steps = proposal.agent_steps?.map(step => JSON.stringify(step)) ?? []

// AFTER:
const steps = proposal.agent_steps_readable ?? proposal.agent_steps?.map(s => s.source_id) ?? []
```

---

## Step 7 — Verify the Yes/No Budget Fix (BUG-6)

**File:** `src/app/routers/recommend.py`
**Lines:** ~2913–2930

The exploration confirmed the fix IS present in the prompt. But verify the actual prompt text at those lines includes both of these:

```python
# recommend.py ~line 2913–2930 — verify these lines are in the prompt:
# "Answer the user's question DIRECTLY in the first sentence."
# "If it is a yes/no question (e.g. 'Is $1,800 enough?'), answer yes or no first."
```

If the prompt includes these but responses are still robotic, the issue is the Ollama model (`llama3.3:8b` for simple queries) not following instructions. Fix: ensure budget questions score ≥5 complexity so they route to mixtral:

```python
# llm_provider.py — add to score_query_complexity(), after existing signals
# Budget yes/no questions should get medium model minimum
budget_yn_patterns = [
    "is $", "is that enough", "is my budget", "enough for", "afford",
    "can i get", "will $", "how much does"
]
if any(p in q_lower for p in budget_yn_patterns):
    signals["budget_question"] = True
    score += 2   # forces medium model
```

---

## Response Quality Checklist

### Before/After for Each Pattern

| Raw / Robotic | Business-Readable |
|---------------|-------------------|
| `{"manipulation_score": 0.847, "splice_score": 0.71}` | "This image shows strong indicators of manipulation and should not be used as evidence." |
| `ELA_splice_score: 0.847; copy_move_detected: True` | "Image has been flagged — areas appear copied and spliced. Recommend manual verification." |
| `fraud_risk: high (0.82) — signals: device_fingerprint_mismatch, session_hijack_indicators` | "High fraud risk (82%). Flagged: device mismatch, session anomaly. Hold for manual review." |
| `I found 3 matches between $800–$1800` | "Yes, $1,800 is enough — here are 3 gaming laptops that fit, starting at $1,299." |
| `anomaly: z=3.4 in domain=refunds` | "Refund rate is 3.4× above normal for this hour — this warrants investigation." |
| `NLP_Search_Agent → Candidate_Retrieval_Agent → Product_Ranking_Agent` | "Understood your query → Searched the catalog → Ranked by relevance" |
| `ring_candidates: [{degree: 7, node: "dev:ABC-123"}]` | "1 high-risk cluster: 7 accounts sharing device ABC-123 in Melbourne." |
| `CVE-2025-54236 severity=critical package=magento-payment cvss=9.1` | "Critical security issue in magento-payment (CVE-2025-54236). Update to version 2.4.7 immediately." |
| `cv_triage: severity=major damage_type=physical component=display` | "Image shows significant physical damage to the display." |

---

## Files Summary

| File | Change | Why |
|------|--------|-----|
| NEW `src/app/services/response_normalizer.py` | Create | Central translation layer |
| `src/app/routers/chat_stream.py` line ~75 | Edit | Polish answer before SSE emission |
| `src/app/routers/vision.py` | Edit | CV/forensics → plain English |
| `src/app/services/fraud_scorer.py` | Add method | Merchant-safe fraud result |
| `src/app/services/anomaly_detector.py` | Already has `plain_english` | Just make sure it's surfaced |
| `src/app/routers/support.py` | Edit | Remove raw FAQ similarity scores |
| `src/app/services/llm_provider.py` | Edit | Budget questions → force medium model |
| `frontend/src/components/ChatMessage` | Edit | Render `agent_steps_readable` |
