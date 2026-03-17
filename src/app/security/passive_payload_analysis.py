from __future__ import annotations

from typing import Any, Dict, List


_HYPOTHESIS_TO_MITRE: Dict[str, List[str]] = {
    "lolbin_command_sequence": ["T1218", "T1059.001", "T1105"],
    "prompt_injection":        ["AML.T0043", "T1566.002"],
    "data_exfiltration":       ["T1041", "T1020"],
    "c2_beacon":               ["T1071.001", "T1105", "T1573.002"],
    "payment_fraud":           ["T1566.002", "T1204.001"],
    "ransomware":              ["T1486", "T1059", "T1490"],
    "macros":                  ["T1566.001", "T1204.002", "T1059.005"],
    "steg_unknown_payload":    ["T1027.001", "T1027"],
    "unknown":                 [],
}

# PASTA stage per hypothesis — maps to the framework_correlation stage names
_HYPOTHESIS_TO_PASTA: Dict[str, str] = {
    "prompt_injection":        "Stage4 — Exploitation & Vulnerability Analysis",
    "ransomware":              "Stage6 — Attack Modeling & Risk Response",
    "macros":                  "Stage4 — Exploitation & Vulnerability Analysis",
    "payment_fraud":           "Stage5 — Weakness & Vulnerability Analysis",
    "lolbin_command_sequence": "Stage4 — Exploitation & Vulnerability Analysis",
    "data_exfiltration":       "Stage5 — Weakness & Vulnerability Analysis",
    "c2_beacon":               "Stage4 — Exploitation & Vulnerability Analysis",
    "steg_unknown_payload":    "Stage4 — Exploitation & Vulnerability Analysis",
    "unknown":                 "Stage2 — Technical Scope Definition",
}

# Per-hypothesis decode path — communicates safe handling instruction to analysts
_HYPOTHESIS_TO_DECODE_PATH: Dict[str, str] = {
    "prompt_injection":        "safe_passive_decode_only",
    "ransomware":              "sandbox_required_do_not_execute",
    "macros":                  "sandbox_required_do_not_execute",
    "payment_fraud":           "safe_passive_decode_only",
    "lolbin_command_sequence": "lolbin_command_decode",
    "data_exfiltration":      "sandbox_required_do_not_execute",
    "c2_beacon":               "sandbox_required_do_not_execute",
    "steg_unknown_payload":    "safe_passive_decode_only",
    "unknown":                 "safe_passive_decode_only",
}

# Human-readable labels for boolean signal keys displayed in the UI
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

    # Pull LSB-extracted content out of steg_details (set by steg_detector._try_extract_lsb_content)
    # and treat it as first-class decoded artifact for hypothesis classification.
    steg_decoded_content = str(steg_details.get("decoded_content") or "").strip()

    # IMPORTANT: hypothesis classification must be driven by payload CONTENT only, not filename.
    # Including the filename in content_text causes false positives where the hypothesis fires
    # on file-naming conventions (e.g. "steg-c2_beacon-...png" → c2_beacon) rather than on
    # actual decoded content. The filename is used ONLY for payload_type extension heuristics.
    content_text = _compact_text(extracted_text or "", steg_decoded_content, payloads, steg_explanations, steg_details)
    filename_lower = (filename or "").strip().lower()

    decoded_artifact_available = (
        bool(payloads)
        or bool(str(extracted_text or "").strip())
        or bool(steg_decoded_content)
        or bool(steg_details)
    )

    payload_type = "unknown"
    if payloads:
        payload_type = "qr"
    elif str(extracted_text or "").strip():
        payload_type = "embedded_text"
    elif steg_decoded_content:
        payload_type = "steg_decoded_payload"
    elif steg_details:
        payload_type = "steg_metadata"
    elif filename_lower.endswith((".docm", ".xlsm", ".pptm", ".doc", ".xls", ".ppt")):
        payload_type = "office_macro_candidate"

    hypothesis = "unknown"
    if sigs.get("qr_prompt_injection") or _contains_any(
        content_text, ["ignore previous", "ignore all previous", "system prompt", "developer message",
                        "prompt injection", "system override", "jailbreak", "disregard previous",
                        "forget your instructions", "new instructions:", "act as", "roleplay as",
                        "you are now an unrestricted", "unrestricted assistant"]
    ):
        hypothesis = "prompt_injection"
    # Payment fraud first: PayID/BSB/bank-redirect payloads may contain bitcoin without being ransomware
    elif sigs.get("payment_social_engineering") or sigs.get("pci_card_exposed") or sigs.get("crypto_payment_uri") or _contains_any(
        content_text, ["payid", "bsb:", "send payment", "payment redirect", "bitcoin:", "bc1q",
                       "scan to pay", "bank transfer", "account:", "direct debit", "payment to"]
    ):
        hypothesis = "payment_fraud"
    elif sigs.get("ransomware_indicator") or _contains_any(
        content_text, ["ransom", "decrypt", "unlock files", "pay within", "your files are encrypted",
                       "files are locked", "pay the ransom", "restore your files", "deadline"]
    ):
        hypothesis = "ransomware"
    # LOLBin before macros: mshta/macro.hta is a LOLBin pattern, not an Office macro
    elif _contains_any(
        content_text, ["lolbin", "powershell", "rundll32", "regsvr32", "mshta", "certutil", "wscript", "cscript", "bitsadmin",
                        "-encodedcommand", "-enc ", "invoke-expression", "iex(", "invoke-webrequest",
                        "net.webclient", "downloadstring", "downloadfile", "start-process",
                        "amsiutils", "[reflection.assembly]", "memorystream", "frombase64string",
                        "certutil -urlcache", "certutil -decode", "regsvr32 /s", "regsvr32 /u"]
    ):
        hypothesis = "lolbin_command_sequence"
    # C2 before data_exfil: a beacon payload may include "exfil" as a secondary action
    elif _contains_any(
        content_text, ["c2_beacon", "c2beacon", "test_beacon", "type: test_beacon",
                        "poll every", "heartbeat", "beacon:interval", "beaconing", "dns_tunnel",
                        "callback", "check-in", "command and control", "c2_server", "c2server",
                        "sleeptime", "jitter=", "interval=", "dst="]
    ) and _contains_any(content_text, ["beacon", "callback", "c2", "check-in", "interval"]):
        hypothesis = "c2_beacon"
    elif _contains_any(
        content_text, ["exfil", "data exfiltration", "upload archive", "send archive", "exfiltrate", "upload to", "send to remote",
                        "zip and send", "compress archive", "curl -f", "wget -q", "scp -r", "rclone copy",
                        "sensitivefiles", "dump credentials", "shadow copy", "ntds.dit",
                        "action.*exfiltrate", "collect.*api_keys", "collect.*user_data"]
    ):
        hypothesis = "data_exfiltration"
    elif _contains_any(
        content_text, ["office macro", "vba macro", "enable content", "docm", "xlsm",
                        "sub autoopen", "sub auto_open", "document_open", "workbook_open",
                        "shell(", "createobject", "wscript.shell", "shell.application",
                        "activex", "ddeauto", "fieldcode", "includetext", "vba"]
    ):
        hypothesis = "macros"
    elif bool(sigs.get("steg_suspicious")) and not decoded_artifact_available:
        # Steg is flagged but no readable payload decoded — honest unknown with steg signal
        hypothesis = "steg_unknown_payload"

    # Wire ransomware_indicator back into signals so PASTA logic in observer.py and
    # framework_correlation._pasta() can promote to Stage6.
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
        "signals_updated": sigs,
    }

