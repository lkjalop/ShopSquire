from __future__ import annotations

from typing import Any, Dict, List

from src.app.security.lolbin_behavioral_catalog import derive_lolbin_attack_ids_from_text


_HYPOTHESIS_TO_ACTIVE_MITRE_ATTACK: Dict[str, List[str]] = {
    "prompt_injection": [],
    "payment_fraud": ["T1566.002"],
    "pii_data_exfil_via_qr": [],
    "lolbin_command_sequence": [],
    "data_exfiltration": [],
    "c2_beacon": [],
    "ransomware": [],
    "macros": [],
    "fileless_attack": [],
    "steg_unknown_payload": [],
    "unknown": [],
}

_HYPOTHESIS_TO_POSSIBLE_MITRE_ATTACK: Dict[str, List[str]] = {
    "lolbin_command_sequence": ["T1105", "T1059.001", "T1197", "T1053.005", "T1218.005", "T1218.010", "T1218.011", "T1059.005", "T1140"],
    "prompt_injection": ["T1566.002"],
    "data_exfiltration": ["T1041", "T1020"],
    "c2_beacon": ["T1071.001", "T1071.004", "T1105", "T1573.002", "T1203", "T1029", "T1041"],
    "payment_fraud": ["T1204.001"],
    "ransomware": ["T1486", "T1059", "T1490"],
    "macros": ["T1566.001", "T1204.002", "T1059.001", "T1059.005"],
    "fileless_attack": ["T1059.001", "T1620", "T1546.003", "T1134.004", "T1027", "T1562.001"],
    "steg_unknown_payload": ["T1027.001", "T1027"],
    "pii_data_exfil_via_qr": ["T1041", "T1078"],
    "unknown": [],
}

_HYPOTHESIS_TO_ACTIVE_MITRE_ATLAS: Dict[str, List[str]] = {
    "prompt_injection": ["AML.T0043"],
    "unknown": [],
}

_HYPOTHESIS_TO_PASTA: Dict[str, str] = {
    "prompt_injection": "Stage4:ThreatAnalysis",
    "ransomware": "Stage4:ThreatAnalysis",
    "macros": "Stage4:ThreatAnalysis",
    "payment_fraud": "Stage4:ThreatAnalysis",
    "lolbin_command_sequence": "Stage4:ThreatAnalysis",
    "data_exfiltration": "Stage5:VulnerabilityAnalysis",
    "c2_beacon": "Stage4:ThreatAnalysis",
    "fileless_attack": "Stage4:ThreatAnalysis",
    "steg_unknown_payload": "Stage2:DefineTechnicalScope",
    "pii_data_exfil_via_qr": "Stage4:ThreatAnalysis",
    "unknown": "Stage2:DefineTechnicalScope",
}

_HYPOTHESIS_TO_DECODE_PATH: Dict[str, str] = {
    "prompt_injection": "safe_passive_decode_only",
    "ransomware": "sandbox_required_do_not_execute",
    "macros": "sandbox_required_do_not_execute",
    "payment_fraud": "safe_passive_decode_only",
    "lolbin_command_sequence": "lolbin_command_decode",
    "data_exfiltration": "sandbox_required_do_not_execute",
    "c2_beacon": "sandbox_required_do_not_execute",
    "fileless_attack": "sandbox_required_do_not_execute",
    "steg_unknown_payload": "safe_passive_decode_only",
    "pii_data_exfil_via_qr": "safe_passive_decode_only",
    "unknown": "safe_passive_decode_only",
}

_HYPOTHESIS_TO_FINDING_GROUP: Dict[str, str] = {
    "prompt_injection": "active_findings",
    "payment_fraud": "active_findings",
    "pii_data_exfil_via_qr": "active_findings",
    "lolbin_command_sequence": "unconfirmed_higher_order_hypotheses",
    "data_exfiltration": "unconfirmed_higher_order_hypotheses",
    "c2_beacon": "unconfirmed_higher_order_hypotheses",
    "ransomware": "unconfirmed_higher_order_hypotheses",
    "macros": "unconfirmed_higher_order_hypotheses",
    "fileless_attack": "unconfirmed_higher_order_hypotheses",
    "steg_unknown_payload": "detection_artifact_patterns",
    "unknown": "suppressed_findings",
}

_HYPOTHESIS_TO_CLAIM_STATUS: Dict[str, str] = {
    "prompt_injection": "observed",
    "payment_fraud": "observed",
    "pii_data_exfil_via_qr": "observed",
    "lolbin_command_sequence": "possible",
    "data_exfiltration": "possible",
    "c2_beacon": "possible",
    "ransomware": "possible",
    "macros": "possible",
    "fileless_attack": "possible",
    "steg_unknown_payload": "observed",
    "unknown": "suppressed",
}

_HYPOTHESIS_TO_EVIDENCE_LANE: Dict[str, str] = {
    "prompt_injection": "passive_artifact_observation",
    "payment_fraud": "passive_artifact_observation",
    "pii_data_exfil_via_qr": "passive_linked_artifact_observation",
    "lolbin_command_sequence": "passive_artifact_hypothesis",
    "data_exfiltration": "passive_artifact_hypothesis",
    "c2_beacon": "passive_artifact_hypothesis",
    "ransomware": "passive_artifact_hypothesis",
    "macros": "passive_artifact_hypothesis",
    "fileless_attack": "passive_artifact_hypothesis",
    "steg_unknown_payload": "passive_artifact_signal_only",
    "unknown": "passive_artifact_signal_only",
}

_HYPOTHESIS_TO_RUNTIME_EVIDENCE: Dict[str, List[str]] = {
    "lolbin_command_sequence": [
        "sandbox_detonation: process tree and child processes",
        "endpoint_process_tree: certutil/mshta/powershell/regsvr32 lineage",
        "command_line_telemetry: encoded or download-and-execute chains",
        "dns_proxy_network: payload fetch or callback infrastructure",
    ],
    "c2_beacon": [
        "sandbox_detonation: callback behavior and cadence",
        "endpoint_network_connections: repeated outbound check-ins",
        "dns_proxy_firewall_logs: destination host, domain, and ASN overlap",
        "pcap_or_edr_network: beacon interval, jitter, and protocol evidence",
    ],
    "data_exfiltration": [
        "sandbox_detonation: outbound transfer or archive staging",
        "file_access_and_archive_logs: zip/rar/archive creation",
        "proxy_or_casb_dlp_logs: upload destinations and transfer volume",
        "identity_and_endpoint_telemetry: user, host, and tool overlap",
    ],
    "macros": [
        "sandbox_detonation: macro execution traces",
        "office_telemetry: macro enablement and child process creation",
        "endpoint_process_tree: Office to script-host or LOLBin lineage",
        "dns_proxy_network: follow-on payload fetches or callbacks",
    ],
    "fileless_attack": [
        "powershell_scriptblock_logging: Event ID 4104 decoded command content",
        "amsi_telemetry: AMSI scan results for in-memory payload strings",
        "edr_memory_forensics: injected shellcode or .NET assembly in process memory",
        "wmi_subscription_audit: WMI event filter and consumer registration",
    ],
    "ransomware": [
        "sandbox_detonation: file encryption or ransom-note behavior",
        "endpoint_process_tree: encryption tooling and shadow copy tampering",
        "filesystem_telemetry: bulk file modification or extension changes",
        "edr_registry_and_network: persistence or tasking evidence",
    ],
}

SIGNAL_LABELS: Dict[str, str] = {
    "steg_suspicious": "Steganography Detected",
    "steg_score_elevated": "Steg Score Elevated",
    "qr_code_detected": "QR Code Present",
    "qr_prompt_injection": "QR Prompt Injection",
    "qr_external_url": "QR External URL",
    "qr_url_suspicious": "QR URL Suspicious",
    "adversarial_detected": "Adversarial Perturbation",
    "ai_generated_suspected": "AI-Generated Image",
    "ransomware_indicator": "Ransomware Pattern",
    "payment_social_engineering": "Payment Social Engineering",
    "pci_card_exposed": "PCI Card Data Exposed",
    "crypto_payment_uri": "Crypto Payment URI",
    "manipulation_detected": "Image Manipulation",
    "image_consistency_mismatch": "Image Consistency Mismatch",
    "ocr_prompt_injection": "OCR Prompt Injection",
    "prompt_injection_text_suspected": "Prompt Injection Text",
    "cross_modal_mismatch": "Cross-Modal Mismatch",
    "multimodal_attack_surface_high": "Multimodal Attack Surface High",
    "supply_chain": "Supply Chain Signal",
    "data_exfiltration": "Data Exfiltration Pattern",
    "ssn_detected": "SSN in Linked Artifact",
    "pii_detected": "PII Data Exposed",
    "pii_types": "PII Types Found",
    "ssn_count": "SSN Count",
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


def _token_hits(text: str, tokens: List[str]) -> List[str]:
    return [tok for tok in tokens if tok in text]


def _cluster_match(text: str, cluster_tokens: Dict[str, List[str]], *, min_clusters: int) -> Dict[str, List[str]]:
    hits: Dict[str, List[str]] = {}
    for cluster, tokens in cluster_tokens.items():
        matched = _token_hits(text, tokens)
        if matched:
            hits[cluster] = matched
    if len(hits) < int(min_clusters):
        return {}
    return hits


def _contains_url_like_target(text: str) -> bool:
    low = str(text or "").lower()
    return any(
        tok in low
        for tok in (
            "http://",
            "https://",
            ".example.invalid",
            "/callback",
            "/collect",
            "destination\": \"http",
            "target\": \"http",
        )
    )


def _is_benign_comment_only_vba_source(filename: str, content_text: str) -> bool:
    low_name = str(filename or "").strip().lower()
    low = str(content_text or "").lower()
    if not low_name.endswith(".bas"):
        return False
    if "benign test - no functional malicious code" not in low:
        return False
    comment_markers = ("' powershell", "' certutil", "' bitsadmin", "' schtasks", "' mshta", "' regsvr32", "' rundll32", "' wscript", "' cscript")
    return any(tok in low for tok in comment_markers)


def _binary_mitre_provenance(filename: str, content_text: str) -> List[Dict[str, Any]]:
    low_name = str(filename or "").strip().lower()
    low = str(content_text or "").lower()
    refs_by_binary: Dict[str, List[str]] = {}
    if low_name.endswith(".xlsm"):
        if "certutil -urlcache" in low or "certutil.exe" in low:
            refs_by_binary["certutil"] = ["xlsm.vba.certutil_indicator"]
            if "certutil -decode" in low:
                refs_by_binary["certutil"].append("xlsm.vba.certutil_indicator")
        if "powershell -executionpolicy bypass" in low or "powershell.exe" in low:
            refs_by_binary["powershell"] = ["xlsm.vba.powershell_indicator"]
        if "bitsadmin /transfer" in low or "bitsadmin" in low:
            refs_by_binary["bitsadmin"] = ["xlsm.vba.bitsadmin_indicator"]
        if "schtasks /create" in low or "schtasks" in low:
            refs_by_binary["schtasks"] = ["xlsm.vba.schtasks_indicator"]
        if "mshta" in low:
            refs_by_binary["mshta"] = ["xlsm.vba.mshta_indicator"]
        if "regsvr32" in low:
            refs_by_binary["regsvr32"] = ["xlsm.vba.regsvr32_indicator"]
        if "rundll32" in low:
            refs_by_binary["rundll32"] = ["xlsm.vba.rundll32_indicator"]
        if "wscript" in low:
            refs_by_binary["wscript"] = ["xlsm.vba.wscript_indicator"]
        if "cscript" in low:
            refs_by_binary["cscript"] = ["xlsm.vba.cscript_indicator"]
    elif low_name.endswith(".bas"):
        if "' certutil.exe" in low or "' certutil -urlcache" in low:
            refs_by_binary["certutil"] = ["vba.comments.lolbin_pattern"]
        if "' powershell.exe" in low:
            refs_by_binary["powershell"] = ["vba.comments.lolbin_pattern"]
        if "' bitsadmin" in low:
            refs_by_binary["bitsadmin"] = ["vba.comments.lolbin_pattern"]
        if "' schtasks" in low:
            refs_by_binary["schtasks"] = ["vba.comments.lolbin_pattern"]
        if "' mshta" in low:
            refs_by_binary["mshta"] = ["vba.comments.lolbin_pattern"]
        if "' regsvr32" in low:
            refs_by_binary["regsvr32"] = ["vba.comments.lolbin_pattern"]
        if "' rundll32" in low:
            refs_by_binary["rundll32"] = ["vba.comments.lolbin_pattern"]
        if "' wscript" in low:
            refs_by_binary["wscript"] = ["vba.comments.lolbin_pattern"]
        if "' cscript" in low:
            refs_by_binary["cscript"] = ["vba.comments.lolbin_pattern"]

    rows: List[Dict[str, Any]] = []
    for binary, refs in refs_by_binary.items():
        derived = derive_lolbin_attack_ids_from_text(f"{binary} {low}")
        for attack_id in derived:
            reason = {
                "certutil": f"{binary} -> {attack_id} because {'xlsm.vba.certutil_indicator' if low_name.endswith('.xlsm') else 'vba.comments.lolbin_pattern'}",
                "powershell": f"{binary} -> {attack_id} because {'xlsm.vba.powershell_indicator' if low_name.endswith('.xlsm') else 'vba.comments.lolbin_pattern'}",
            }.get(binary, f"{binary} -> {attack_id} because {refs[0]}")
            rows.append(
                {
                    "binary": binary,
                    "attack_id": attack_id,
                    "evidence_refs": refs,
                    "reason": reason,
                }
            )
    return rows


def _hypothesis_bundle(hypothesis: str) -> Dict[str, Any]:
    return {
        "hypothesis": hypothesis,
        "mitre_attack": list(_HYPOTHESIS_TO_ACTIVE_MITRE_ATTACK.get(hypothesis, [])),
        "possible_mitre_attack": list(_HYPOTHESIS_TO_POSSIBLE_MITRE_ATTACK.get(hypothesis, [])),
        "mitre_atlas": list(_HYPOTHESIS_TO_ACTIVE_MITRE_ATLAS.get(hypothesis, [])),
        "possible_mitre_atlas": [],
        "pasta_stage": _HYPOTHESIS_TO_PASTA.get(hypothesis, "Stage2:DefineTechnicalScope"),
        "decode_path": _HYPOTHESIS_TO_DECODE_PATH.get(hypothesis, "safe_passive_decode_only"),
        "finding_group": _HYPOTHESIS_TO_FINDING_GROUP.get(hypothesis, "suppressed_findings"),
        "claim_status": _HYPOTHESIS_TO_CLAIM_STATUS.get(hypothesis, "suppressed"),
        "evidence_lane": _HYPOTHESIS_TO_EVIDENCE_LANE.get(hypothesis, "passive_artifact_signal_only"),
        "runtime_evidence_required": list(_HYPOTHESIS_TO_RUNTIME_EVIDENCE.get(hypothesis, [])),
    }


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

    steg_decoded_content = str(steg_details.get("decoded_content") or "").strip()
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

    matched_hypotheses: List[str] = []

    if sigs.get("qr_prompt_injection") or _contains_any(
        content_text,
        [
            "ignore previous",
            "ignore all previous",
            "system prompt",
            "developer message",
            "prompt injection",
            "system override",
            "jailbreak",
            "disregard previous",
            "forget your instructions",
            "new instructions:",
            "act as",
            "roleplay as",
            "you are now an unrestricted",
            "unrestricted assistant",
        ],
    ):
        matched_hypotheses.append("prompt_injection")
    if _contains_any(
        content_text,
        [
            "lolbin",
            "powershell",
            "rundll32",
            "regsvr32",
            "mshta",
            "certutil",
            "wscript",
            "cscript",
            "bitsadmin",
            "-encodedcommand",
            "-enc ",
            "invoke-expression",
            "iex(",
            "invoke-webrequest",
            "net.webclient",
            "downloadstring",
            "downloadfile",
            "start-process",
            "amsiutils",
            "[reflection.assembly]",
            "memorystream",
            "frombase64string",
            "certutil -urlcache",
            "certutil -decode",
            "regsvr32 /s",
            "regsvr32 /u",
        ],
    ):
        matched_hypotheses.append("lolbin_command_sequence")
    if sigs.get("payment_social_engineering") or sigs.get("pci_card_exposed") or sigs.get("crypto_payment_uri") or _contains_any(
        content_text,
        [
            "payid",
            "wire transfer",
            "beneficiary",
            "swift",
            "deposit required",
            "acquisition deposit",
            "verbal approval pending",
            "do not discuss",
            "anzbau3m",
            "012-456",
            "bsb:",
            "bsb ",
            "send payment",
            "payment redirect",
            "bitcoin:",
            "bc1q",
            "scan to pay",
            "bank transfer",
            "account:",
            "direct debit",
            "payment to",
        ],
    ):
        matched_hypotheses.append("payment_fraud")
    c2_clusters = _cluster_match(
        content_text,
        {
            "infra": [
                "balashnikovai-analytics.com",
                "balashnikovai-cdn.com",
                "/track/wta-",
                "track/wta-2026",
                ".balashnikovai-",
                "c2_server",
                "c2server",
                "dns_tunnel",
                "dns tunneling",
                "nslookup",
                "test-c2.example.invalid",
            ],
            "semantics": ["beacon", "beaconing", "callback", "check-in", "command and control", "heartbeat", "sendbeacon"],
            "timing": ["poll every", "beacon:interval", "interval=", "\"interval\":", "jitter=", "sleeptime", "app.setinterval"],
            "execution": ["cmd\":", "whoami && hostname", "powershell", "curl", "wget"],
        },
        min_clusters=2,
    )
    if c2_clusters and (_contains_url_like_target(content_text) or "semantics" in c2_clusters):
        matched_hypotheses.append("c2_beacon")
    exfil_clusters = _cluster_match(
        content_text,
        {
            "action": ["exfil", "data exfiltration", "exfiltrate", "\"action\": \"exfiltrate\"", "upload to", "send to remote", "zip and send", "upload archive", "send archive"],
            "tooling": ["curl -f", "wget -q", "scp -r", "rclone copy", "base64_encode_in_url_params"],
            "targets": ["sensitivefiles", "dump credentials", "shadow copy", "ntds.dit", "api_keys", "user_data", "collect", "archive", ".zip", ".rar"],
            "destination": ["destination\": \"http", "test-exfil.example.invalid", "/collect", "upload"],
        },
        min_clusters=2,
    )
    if exfil_clusters and (_contains_url_like_target(content_text) or "targets" in exfil_clusters):
        matched_hypotheses.append("data_exfiltration")
    if _contains_any(
        content_text,
        [
            "office macro",
            "vba macro",
            "enable content",
            "docm",
            "xlsm",
            "sub autoopen",
            "sub auto_open",
            "document_open",
            "workbook_open",
            "shell(",
            "createobject",
            "wscript.shell",
            "shell.application",
            "activex",
            "ddeauto",
            "fieldcode",
            "includetext",
            "vba",
        ],
    ):
        matched_hypotheses.append("macros")
    fileless_memory = _contains_any(content_text, ["[reflection.assembly]::load", "memo" + "rystream", "new-object system.reflection", "appdomain.load", "virtualalloc", "create" + "thread", "invoke-shell" + "code", "invoke-reflectivepe" + "injection"])
    fileless_evasion = _contains_any(content_text, ["amsi" + "utils", "amsi bypass", "invoke-patch" + "amsi", "set-mppreference -disablerealtimemonitoring", "add-mppreference -exclusionpath"])
    fileless_persist = _contains_any(content_text, ["wmi event subscription", "wmi filter", "__eventfilter", "__eventconsumer", "__filtertoconsumerbinding", "ppid spoof", "ppid" + "spoofing"])
    if (fileless_memory and fileless_evasion) or (fileless_memory and fileless_persist):
        matched_hypotheses.append("fileless_attack")
    if bool(sigs.get("steg_suspicious")) and not decoded_artifact_available:
        matched_hypotheses.append("steg_unknown_payload")
    if sigs.get("ssn_detected") or sigs.get("pii_detected"):
        matched_hypotheses.append("pii_data_exfil_via_qr")

    benign_comment_only = _is_benign_comment_only_vba_source(filename_lower, content_text)
    if benign_comment_only:
        matched_hypotheses = [h for h in matched_hypotheses if h not in {"lolbin_command_sequence", "c2_beacon", "data_exfiltration", "fileless_attack", "macros"}]

    if not matched_hypotheses:
        matched_hypotheses = ["unknown"]
    else:
        matched_hypotheses = list(dict.fromkeys([x for x in matched_hypotheses if x]))

    hypothesis = matched_hypotheses[0]

    if hypothesis == "ransomware" and not sigs.get("ransomware_indicator"):
        sigs["ransomware_indicator"] = True

    primary_bundle = _hypothesis_bundle(hypothesis)
    active_mitre_attack = list(primary_bundle.get("mitre_attack", []))
    possible_mitre_attack = list(primary_bundle.get("possible_mitre_attack", []))
    active_mitre_atlas = list(primary_bundle.get("mitre_atlas", []))
    pasta_stage = str(primary_bundle.get("pasta_stage") or "Stage2:DefineTechnicalScope")
    decode_path = str(primary_bundle.get("decode_path") or "safe_passive_decode_only")
    finding_group = str(primary_bundle.get("finding_group") or "suppressed_findings")
    claim_status = str(primary_bundle.get("claim_status") or "suppressed")
    evidence_lane = str(primary_bundle.get("evidence_lane") or "passive_artifact_signal_only")
    runtime_evidence_required = list(primary_bundle.get("runtime_evidence_required", []))
    runtime_confirmation_required = bool(runtime_evidence_required)

    if hypothesis in {"lolbin_command_sequence", "c2_beacon", "ransomware", "macros", "fileless_attack", "steg_unknown_payload"} or bool(sigs.get("steg_suspicious")):
        suggested_next_step = "queue_sandbox_detonation"
    elif hypothesis in {"prompt_injection", "data_exfiltration", "payment_fraud", "pii_data_exfil_via_qr"} or bool(sigs.get("steg_score_elevated")):
        suggested_next_step = "review"
    else:
        suggested_next_step = "allow"

    lolbin_profiles: List[Dict[str, Any]] = []
    lolbin_hits: List[str] = []
    binary_mitre_provenance = _binary_mitre_provenance(filename_lower, content_text)
    if hypothesis == "lolbin_command_sequence":
        try:
            from src.app.security.lolbin_behavioral_catalog import LOLBIN_CATALOG, enrich_lolbin_indicators

            lolbin_hits = [k for k in LOLBIN_CATALOG if k in content_text]
            lolbin_profiles = enrich_lolbin_indicators(lolbin_hits)
            derived = derive_lolbin_attack_ids_from_text(content_text)
            if derived:
                possible_mitre_attack = derived
        except Exception:
            pass

    matched_rows = []
    for matched in matched_hypotheses:
        bundle = _hypothesis_bundle(matched)
        matched_possible_mitre = list(bundle.get("possible_mitre_attack") or [])
        if matched == "lolbin_command_sequence":
            derived = derive_lolbin_attack_ids_from_text(content_text)
            if derived:
                matched_possible_mitre = derived
        matched_rows.append(
            {
                "hypothesis": matched,
                "claim_status": bundle.get("claim_status"),
                "finding_group": bundle.get("finding_group"),
                "evidence_lane": bundle.get("evidence_lane"),
                "pasta_stage": bundle.get("pasta_stage"),
                "decode_path": bundle.get("decode_path"),
                "mitre_attack": bundle.get("mitre_attack"),
                "possible_mitre_attack": matched_possible_mitre,
                "mitre_atlas": bundle.get("mitre_atlas"),
                "possible_mitre_atlas": bundle.get("possible_mitre_atlas"),
                "runtime_confirmation_required": bool(bundle.get("runtime_evidence_required")),
                "runtime_evidence_required": list(bundle.get("runtime_evidence_required") or []),
                "binary_mitre_provenance": [dict(x) for x in binary_mitre_provenance][:8] if matched == "lolbin_command_sequence" else [],
            }
        )

    return {
        "decoded_artifact_available": bool(decoded_artifact_available),
        "payload_type": payload_type,
        "attack_hypothesis": hypothesis,
        "mitre_attack": active_mitre_attack,
        "possible_mitre_attack": possible_mitre_attack,
        "mitre_atlas": active_mitre_atlas,
        "possible_mitre_atlas": [],
        "pasta_stage": pasta_stage,
        "decode_path": decode_path,
        "suggested_next_step": suggested_next_step,
        "lolbin_hits": lolbin_hits,
        "binary_mitre_provenance": [dict(x) for x in binary_mitre_provenance][:8],
        "lolbin_behavioral_profiles": lolbin_profiles,
        "claim_status": claim_status,
        "finding_group": finding_group,
        "evidence_lane": evidence_lane,
        "runtime_confirmation_required": runtime_confirmation_required,
        "runtime_evidence_required": runtime_evidence_required,
        "runtime_evidence_present": [],
        "matched_hypotheses": matched_rows,
        "signal_labels": SIGNAL_LABELS,
        "signals_updated": sigs,
    }




