import json
import re
from typing import Any, Dict, List

try:
    from src.app.services.llm import LLMOrchestrator
except Exception:
    LLMOrchestrator = None
try:
    from src.app.security.observer import analyze_payload
except Exception:
    analyze_payload = None


class PolicyGate:
    """Policy gate with deterministic rule engine and optional LLM enrichment."""

    def __init__(self, flags: Dict[str, Any] | None = None):
        self.flags = flags or {}
        self.llm = None
        try:
            if self.flags.get("POLICY_GATE_USE_LLM") and LLMOrchestrator is not None:
                self.llm = LLMOrchestrator()
        except Exception:
            self.llm = None

    def _rules(self, text: str) -> Dict[str, Any]:
        low = text.lower()
        verdict = "allow"
        reason = "no issues detected"
        mitigations: List[str] = []
        mitre_tags: List[str] = []
        confidence = 0.8

        if not low.strip():
            return {
                "verdict": verdict,
                "reason": "empty input",
                "mitigations": ["request_clarification"],
                "mitre_tags": [],
                "confidence": 0.5,
            }

        # Injection / prompt attacks
        if re.search(r"(?i)(ignore\s+all|override\s+system|system\s*message:|developer\s*override|jailbreak)", low):
            return {
                "verdict": "block",
                "reason": "prompt injection pattern",
                "mitigations": ["refuse_request", "log_security_event"],
                "mitre_tags": ["AML.T0043"],
                "confidence": 0.95,
            }

        # Data exfil / secrets / API keys
        if re.search(r"(?i)(api\s*key|secret|token|dump\s+secrets|export\s+keys|system\s+prompt)", low):
            return {
                "verdict": "block",
                "reason": "sensitive data request",
                "mitigations": ["redact_output", "rotate_keys", "security_review"],
                "mitre_tags": ["AML.T0048"],
                "confidence": 0.92,
            }

        # SQLi / XSS heuristics
        if "<script>" in low or "javascript:" in low or "onerror=" in low:
            return {
                "verdict": "block",
                "reason": "possible XSS payload",
                "mitigations": ["sanitize_output", "escape_html"],
                "mitre_tags": ["T1059.007"],
                "confidence": 0.95,
            }
        if "select * from" in low or "union select" in low or "--" in low:
            return {
                "verdict": "block",
                "reason": "possible SQL injection",
                "mitigations": ["parameterize_queries", "escape_sql"],
                "mitre_tags": ["T1190"],
                "confidence": 0.92,
            }

        # Fraud indicators
        if any(k in low for k in ("chargeback", "fraud", "stolen", "price mismatch")):
            return {
                "verdict": "escalate",
                "reason": "fraud indicators",
                "mitigations": ["human_review", "hold_order"],
                "mitre_tags": ["T1598"],
                "confidence": 0.85,
            }

        # Supply chain / dependency tampering requests
        if any(k in low for k in ("supply chain", "sbom", "dependency", "package", "vendor", "third party")):
            return {
                "verdict": "escalate",
                "reason": "supply chain risk review",
                "mitigations": ["verify_dependencies", "manual_approval"],
                "mitre_tags": ["T1195"],
                "confidence": 0.75,
            }

        # Low information / unclear
        if len(low) < 10:
            return {
                "verdict": "escalate",
                "reason": "low-information input",
                "mitigations": ["request_clarification"],
                "mitre_tags": [],
                "confidence": 0.6,
            }

        return {"verdict": verdict, "reason": reason, "mitigations": mitigations, "mitre_tags": mitre_tags, "confidence": confidence}

    def evaluate(self, artifact: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Evaluate an artifact (text/proposal/response) and return a policy verdict.

        Returns a dict with keys: verdict (allow|block|escalate), reason, mitigations,
        mitre_tags (list), confidence (0.0-1.0).
        """
        text = None
        try:
            if isinstance(artifact, str):
                text = artifact
            elif isinstance(artifact, dict):
                text = json.dumps(artifact, ensure_ascii=False)
        except Exception:
            text = str(artifact)

        if not text:
            return {"verdict": "allow", "reason": "no issues detected", "mitigations": [], "mitre_tags": [], "confidence": 0.5}

        rule_out = self._rules(text)

        # If configured, attempt an LLM-based evaluation for richer verdicts
        try:
            if self.llm is not None:
                prompt_obj = {
                    "instruction": "Analyze the following artifact for security, fraud, and policy issues. Return a JSON object with keys: verdict (allow|block|escalate), reason, mitigations (list), mitre_tags (list), confidence (0.0-1.0).",
                    "artifact": artifact,
                }
                model = self.flags.get("POLICY_GATE_MODEL") or None
                client = getattr(self.llm, "client", None)
                if client is not None:
                    prompt = json.dumps(prompt_obj, ensure_ascii=False)
                    out = client._call_ollama_cli(model or client.model, prompt)
                    if out:
                        try:
                            start = out.find('{')
                            if start != -1:
                                j = json.loads(out[start:])
                            else:
                                j = json.loads(out)
                            if isinstance(j, dict) and j.get('verdict'):
                                return {
                                    "verdict": j.get('verdict'),
                                    "reason": j.get('reason'),
                                    "mitigations": j.get('mitigations') or [],
                                    "mitre_tags": j.get('mitre_tags') or [],
                                    "confidence": float(j.get('confidence') or 0.5),
                                }
                        except Exception:
                            pass
        except Exception:
            pass

        # Merge observer signals if available to align with compliance mappings
        if analyze_payload is not None:
            try:
                sec = analyze_payload({"artifact": artifact, "context": context or {}})
                details = sec.get("details") if isinstance(sec, dict) else {}
                if isinstance(details, dict):
                    rule_out["security"] = {
                        "severity": sec.get("severity"),
                        "risk_adj": sec.get("risk_adj"),
                        "signals": details.get("signals"),
                        "owasp_llm_top10": details.get("owasp_llm_top10"),
                        "owasp_agentic_top10": details.get("owasp_agentic_top10"),
                        "owasp_api_top10": details.get("owasp_api_top10"),
                        "mitre_atlas": details.get("mitre_atlas"),
                        "stride_categories": details.get("stride_categories"),
                        "dread_avg": details.get("dread_avg"),
                    }
                    if rule_out.get("verdict") == "allow" and sec.get("severity") in ("high", "critical"):
                        rule_out["verdict"] = "escalate"
                        rule_out["reason"] = "security observer flagged high risk"
                        rule_out["mitigations"] = list(set((rule_out.get("mitigations") or []) + ["security_review"]))
            except Exception:
                pass

        return rule_out
