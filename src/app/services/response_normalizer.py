"""Response normalizer — translates agent/service output into plain business English.

All methods are pure functions (no I/O) so they can be called anywhere in the
request pipeline without adding latency.  Import and call at the point where
a response dict is being assembled before it leaves the backend.

Key transforms:
  - polish_llm_text()       Strip robotic preambles from LLM output
  - forensics_to_english()  ForensicsResult dict → one-sentence verdict
  - fraud_score_to_english() Risk level + signals → merchant-readable summary
  - cv_triage_to_english()  CV triage dict → customer-service-rep sentence
  - agent_steps_to_english() Orchestrator trace steps → human-readable bullets
  - vuln_finding_to_english() VulnFinding dict → non-technical action sentence
  - anomaly_to_english()    AnomalyResult list → plain summary
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class ResponseNormalizer:
    # ------------------------------------------------------------------
    # LLM text polish
    # ------------------------------------------------------------------

    # Robotic preamble patterns to strip from LLM output
    _PREAMBLES = [
        re.compile(r"^Based on (the |your |)information (provided|available)[,.]\s*", re.I),
        re.compile(r"^According to (the |)search results[,.]\s*", re.I),
        re.compile(r"^Here (is|are) (the |)(results?|findings?|matches?)[.:]?\s*", re.I),
        re.compile(r"^I (found|located|retrieved|identified) \d+ (result|match|product)s?\.\s*", re.I),
        re.compile(r"^The search returned \d+ (result|match|product)s?\.\s*", re.I),
        re.compile(r"^(Sure|Certainly|Of course|Absolutely)[,!]\s*", re.I),
        re.compile(r"^Great (question|choice|idea)[,!]\s*", re.I),
    ]

    @classmethod
    def polish_llm_text(cls, text: str, query: str = "") -> str:
        """Light post-processing to reduce robotic preambles and stray JSON."""
        if not text:
            return text

        # Remove stray JSON blobs that leaked through from prompt context
        # Matches simple single-key dicts like {"key": "value"} or {"score": 0.8}
        text = re.sub(r'\{["\'][^"\']{1,40}["\']:\s*[^}]{1,200}\}', "", text)

        # Strip leading robotic preambles
        for pattern in cls._PREAMBLES:
            text = pattern.sub("", text).strip()

        # Normalise bullets to be consistent
        text = re.sub(r"\n\s*[-•–]\s*", "\n• ", text)

        return text.strip()

    # ------------------------------------------------------------------
    # Image forensics
    # ------------------------------------------------------------------

    @staticmethod
    def forensics_to_english(forensics: Dict[str, Any]) -> str:
        """
        Convert ForensicsResult fields to a one-sentence plain-English verdict.
        Input: dict from ImageForensicsService.analyze() (or .to_dict()).
        """
        if not isinstance(forensics, dict):
            return ""

        manip = float(forensics.get("manipulation_score") or 0)
        splice = float(forensics.get("splice_score") or 0)
        copy_move = float(forensics.get("copy_move_score") or 0)
        metadata_flags: List = forensics.get("metadata_flags") or []

        if manip >= 0.8 or splice >= 0.7:
            return (
                "This image shows strong indicators of manipulation and should not be "
                "accepted as authentic evidence for a claim or return."
            )
        if manip >= 0.5 or copy_move >= 0.5:
            parts: List[str] = []
            if copy_move >= 0.5:
                parts.append("areas appear to have been copied and pasted")
            if splice >= 0.4:
                parts.append("portions may have been spliced together")
            if metadata_flags:
                parts.append("metadata inconsistencies were found")
            desc = "; ".join(parts) if parts else "anomalies were detected"
            return (
                f"This image has been flagged for review — {desc}. "
                "Manual verification is recommended."
            )
        if manip >= 0.2:
            return (
                "This image has minor inconsistencies that may be compression artefacts. "
                "No strong evidence of manipulation."
            )
        return "This image appears genuine — no manipulation signals detected."

    # ------------------------------------------------------------------
    # Fraud scoring
    # ------------------------------------------------------------------

    @staticmethod
    def fraud_score_to_english(
        risk_level: str,
        score: float,
        active_signals: Optional[Dict[str, bool]] = None,
    ) -> str:
        """Translate fraud score + signals into a merchant-readable summary."""
        signals = active_signals or {}
        active = [
            k.replace("_", " ")
            for k, v in signals.items()
            if v and not k.startswith("_")
        ]

        pct = f"{score:.0%}" if score <= 1.0 else f"{score:.0f}%"

        if risk_level == "minimal":
            return "No fraud signals detected — this transaction looks normal."
        if risk_level == "low":
            note = f" Minor signal{'s' if len(active) > 1 else ''}: {', '.join(active[:2])}." if active else ""
            return f"Low fraud risk ({pct}).{note}"
        if risk_level == "medium":
            top = ", ".join(active[:3]) if active else "multiple risk factors"
            return (
                f"Medium fraud risk ({pct}). Flagged: {top}. "
                "Consider additional verification before processing."
            )
        # high
        top = ", ".join(active[:4]) if active else "multiple critical factors"
        return (
            f"High fraud risk ({pct}). Triggered: {top}. "
            "Hold for manual review before processing."
        )

    # ------------------------------------------------------------------
    # CV triage
    # ------------------------------------------------------------------

    @staticmethod
    def cv_triage_to_english(triage: Dict[str, Any]) -> str:
        """
        Convert a CV triage result dict to a customer-service-rep-readable sentence.
        Falls through to triage["plain_english"] if already set by VisionReasoningService.
        """
        if not isinstance(triage, dict):
            return ""

        # VisionReasoningService already produced a plain_english field — use it
        existing = (triage.get("plain_english") or "").strip()
        if existing:
            return existing

        severity = (triage.get("severity") or "undetermined").lower()
        damage_type = (triage.get("damage_type") or "unknown").lower()
        component = triage.get("component")

        if triage.get("insufficient_data"):
            return "The image did not contain enough detail to assess damage. Please upload a clearer photo."

        severity_map = {
            "critical":         "severe damage",
            "major":            "significant damage",
            "minor":            "minor damage",
            "undetermined":     "potential damage",
            "insufficient_data":"unclear damage",
        }
        damage_map = {
            "physical":   "physical",
            "cosmetic":   "cosmetic",
            "functional": "functional",
            "packaging":  "packaging",
            "unknown":    "",
        }
        sev_label = severity_map.get(severity, severity)
        dmg_label = damage_map.get(damage_type, "")
        comp_label = f" to the {component}" if component else ""

        parts = " ".join(p for p in [dmg_label, sev_label] if p).strip()
        sentence = f"Image shows {parts}{comp_label}.".replace("  ", " ")
        return sentence[0].upper() + sentence[1:] if sentence else ""

    # ------------------------------------------------------------------
    # Orchestrator agent steps
    # ------------------------------------------------------------------

    _AGENT_LABELS: Dict[str, str] = {
        "NLP_Search_Agent":         "Understood your query",
        "Candidate_Retrieval_Agent":"Searched the product catalog",
        "Product_Ranking_Agent":    "Ranked results by relevance",
        "Fraud_Scoring_Agent":      "Checked for fraud signals",
        "CV_Label_Agent":           "Analysed uploaded image",
        "Inventory_Agent":          "Checked stock availability",
        "NQE":                      "Prepared follow-up questions",
        "Policy_Gate_Agent":        "Applied merchant policies",
        "Security_Observer_Agent":  "Scanned for security threats",
        "Playbook_Engine":          "Ran automated playbook",
        "Email_Security_Engine":    "Analysed email for threats",
    }

    @classmethod
    def agent_steps_to_english(cls, steps: List[Dict[str, Any]]) -> List[str]:
        """Convert raw orchestrator trace steps to human-readable bullet labels."""
        result: List[str] = []
        for step in steps or []:
            agent = step.get("source_id") or step.get("agent") or "System"
            label = cls._AGENT_LABELS.get(agent, agent.replace("_", " "))
            payload = step.get("payload") or {}
            detail = ""
            if "count" in payload:
                detail = f" — {payload['count']} results"
            elif "score" in payload and isinstance(payload["score"], (int, float)):
                detail = f" — {payload['score']:.0%} confidence"
            elif "error" in payload:
                detail = f" — {str(payload['error'])[:60]}"
            result.append(f"{label}{detail}")
        return result

    # ------------------------------------------------------------------
    # Vulnerability findings
    # ------------------------------------------------------------------

    @staticmethod
    def vuln_finding_to_english(finding: Dict[str, Any]) -> str:
        """Ensure a vuln finding has a non-technical plain-English description."""
        existing = (finding.get("plain_english") or "").strip()
        if existing:
            return existing
        cve = finding.get("cve_id") or ""
        pkg = finding.get("package") or "a component"
        sev = finding.get("severity") or "unknown"
        fix = finding.get("fix_version") or finding.get("fixed_version")
        base = f"Security issue in {pkg}{' (' + cve + ')' if cve else ''}: rated {sev}."
        if fix:
            return f"{base} Update to version {fix} to resolve this."
        return f"{base} No official patch yet — isolate or remove this component if possible."

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    @staticmethod
    def anomaly_to_english(anomalies: List[Dict[str, Any]]) -> str:
        """Convert a list of AnomalyResult dicts to a one-line plain summary."""
        if not anomalies:
            return ""
        critical = [a for a in anomalies if a.get("severity") in ("critical", "high")]
        items_src = critical if critical else anomalies
        items = [
            a.get("plain_english") or a.get("domain", "unknown metric").replace("_", " ")
            for a in items_src[:3]
        ]
        items = [i for i in items if i]
        if not items:
            return ""
        if critical:
            return f"Unusual activity detected: {'; '.join(items)}"
        return f"Minor anomalies observed: {'; '.join(items)}"
