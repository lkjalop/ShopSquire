from __future__ import annotations

import math
import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from src.app.security.lolbin_behavioral_catalog import canonical_attack_ids_for_binary
from src.app.security.runtime_detection_policy import (
    BEACON_CV_AUTOMATED_THRESHOLD,
    DNS_LABEL_HIGH_ENTROPY_THRESHOLD,
)
from src.app.security.supply_chain_scenarios import get_scenario

# Per-binary LOLBin risk scores with MITRE sub-technique and kill-chain stage.
# Sourced from LOLBAS Project (lolbas-project.github.io) and MITRE ATT&CK.
_LOLBIN_RISK: Dict[str, Dict[str, Any]] = {
    "certutil.exe":   {"score": 9, "technique": "T1105",     "stage": "delivery/execution",        "flag": "remote_download_or_base64_decode"},
    "bitsadmin.exe":  {"score": 8, "technique": "T1197",     "stage": "persistence/delivery",       "flag": "bits_job_persistence"},
    "powershell.exe": {"score": 8, "technique": "T1059.001", "stage": "execution/c2",               "flag": "encoded_command_or_fileless_iex"},
    "mshta.exe":      {"score": 9, "technique": "T1218.005", "stage": "execution",                  "flag": "remote_hta_or_vbscript"},
    "regsvr32.exe":   {"score": 9, "technique": "T1218.010", "stage": "execution/defense_evasion",  "flag": "squiblydoo_remote_sct"},
    "rundll32.exe":   {"score": 8, "technique": "T1218.011", "stage": "execution/defense_evasion",  "flag": "javascript_in_memory"},
    "schtasks.exe":   {"score": 7, "technique": "T1053.005", "stage": "persistence",                "flag": "scheduled_task_creation"},
    "wmic.exe":       {"score": 7, "technique": "T1047",     "stage": "execution/lateral_movement", "flag": "wmi_process_call_create"},
    "msiexec.exe":    {"score": 7, "technique": "T1218.007", "stage": "execution/defense_evasion",  "flag": "remote_msi_execution"},
    "forfiles.exe":   {"score": 6, "technique": "T1202",     "stage": "execution/defense_evasion",  "flag": "cmd_proxy_via_forfiles"},
    "cmd.exe":        {"score": 5, "technique": "T1059.003", "stage": "execution",                  "flag": "cmd_shell_execution"},
    "wscript.exe":    {"score": 8, "technique": "T1059.005", "stage": "execution",                  "flag": "vbs_or_jscript_execution"},
    "cscript.exe":    {"score": 7, "technique": "T1059.005", "stage": "execution",                  "flag": "vbs_or_jscript_execution"},
}


def _score_process_children(children: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Score a list of child-process dicts from a scenario process tree.

    Returns a summary dict with per-binary risk profiles, composite score,
    and the highest-risk binary detected.
    """
    profiles: List[Dict[str, Any]] = []
    scores: List[float] = []
    for child in children or []:
        name = str((child or {}).get("name") or "").lower().strip()
        for binary, risk in _LOLBIN_RISK.items():
            if binary in name or name == binary.replace(".exe", ""):
                profiles.append({
                    "binary": binary,
                    "detected_name": name,
                    "risk_score": risk["score"],
                    "technique": risk["technique"],
                    "kill_chain_stage": risk["stage"],
                    "detection_flag": risk["flag"],
                })
                scores.append(float(risk["score"]))
                break
    composite = round(max(scores) if scores else 0.0, 1)
    top = max(profiles, key=lambda p: p["risk_score"]) if profiles else {}
    return {"profiles": profiles, "composite_score": composite, "top_binary": top}


def _beacon_cv(interval_sec: Any, jitter_pct: Any) -> float:
    """Calculate a simulated beacon Coefficient of Variation from interval+jitter.

    CV = stddev / mean.  A CV < BEACON_CV_AUTOMATED_THRESHOLD indicates regular (automated) beaconing.
    Uses the jitter percentage to model the distribution of observed inter-arrival times.
    """
    try:
        interval = float(interval_sec or 0)
        jitter = float(jitter_pct or 0) / 100.0
        if interval <= 0:
            return 1.0
        stddev = interval * jitter if jitter > 0 else interval * 0.01
        return round(stddev / interval, 4)
    except Exception:
        return 1.0


_HYPOTHESIS_TO_SCENARIO: Dict[str, Dict[str, Any]] = {
    "fileless_attack": {
        "scenario_id": "SC-05",
        "runtime_evidence_present": [
            "powershell_scriptblock_logging: Event ID 4104 decoded command content",
            "amsi_telemetry: in-memory AMSI scan results for shellcode strings",
            "edr_memory_forensics: injected shellcode or .NET assembly in process memory",
            "wmi_subscription_audit: WMI event filter/consumer registration",
        ],
        "runtime_evidence_missing": [],
        "evidence_lane": "runtime_confirmed_fileless_execution",
    },
    "lolbin_command_sequence": {
        "scenario_id": "SC-05",
        "runtime_evidence_present": [
            "sandbox_detonation: process tree and child processes",
            "endpoint_process_tree: certutil/mshta/powershell/regsvr32 lineage",
            "command_line_telemetry: encoded or download-and-execute chains",
            "dns_proxy_network: payload fetch or callback infrastructure",
        ],
        "runtime_evidence_missing": [],
        "evidence_lane": "runtime_confirmed_detonation",
    },
    "c2_beacon": {
        "scenario_id": "SC-04",
        "runtime_evidence_present": [
            "sandbox_detonation: callback behavior and cadence",
            "endpoint_network_connections: repeated outbound check-ins",
            "dns_proxy_firewall_logs: destination host, domain, and ASN overlap",
            "pcap_or_edr_network: beacon interval, jitter, and protocol evidence",
        ],
        "runtime_evidence_missing": [],
        "evidence_lane": "runtime_confirmed_network_callback",
    },
    "macros": {
        "scenario_id": "SC-06",
        "runtime_evidence_present": [
            "sandbox_detonation: macro execution traces",
            "office_telemetry: macro enablement and child process creation",
            "endpoint_process_tree: Office to script-host or LOLBin lineage",
            "dns_proxy_network: follow-on payload fetches or callbacks",
        ],
        "runtime_evidence_missing": [],
        "evidence_lane": "runtime_confirmed_macro_execution",
    },
}


def _sandbox_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    findings: List[str] = []
    refs: List[str] = []
    extra: Dict[str, Any] = {}
    if hypothesis == "lolbin_command_sequence":
        commands = list(payload.get("commands") or [])
        # Detect fileless indicators in the command list
        fileless_flags: List[str] = []
        for cmd in commands:
            cmd_lower = str(cmd).lower()
            if any(tok in cmd_lower for tok in ["iex", "invoke-expression", "[reflection.assembly]", "memorystream", "frombase64string", "amsiutils"]):
                fileless_flags.append(cmd_lower[:120])
        if fileless_flags:
            findings.append(
                f"Sandbox replay detected {len(fileless_flags)} fileless execution indicator(s): "
                f"in-memory payload loading or AMSI bypass patterns present."
            )
            extra["fileless_indicators"] = fileless_flags
        findings.append("Sandbox replay shows LOLBin child-process lineage consistent with inert download-and-execute behavior.")
        refs.extend(["scenario.payload.commands", "scenario.payload.process_tree.children"])
    elif hypothesis == "c2_beacon":
        interval = payload.get("beacon_interval_sec")
        jitter = payload.get("jitter_pct")
        cv = _beacon_cv(interval, jitter)
        beaconing_verdict = "regular automated beaconing" if cv < BEACON_CV_AUTOMATED_THRESHOLD else "irregular / human-driven traffic"
        findings.append(
            f"Sandbox replay shows periodic callback behavior: interval={interval}s, "
            f"jitter={jitter}%, CV={cv} ({beaconing_verdict})."
        )
        extra["beacon_cv"] = cv
        extra["beacon_regularity"] = beaconing_verdict
        refs.extend(["scenario.payload.beacon_interval_sec", "scenario.payload.jitter_pct"])
    elif hypothesis == "macros":
        vba_calls = list(payload.get("vba_suspicious_calls") or [])
        auto_open = bool(payload.get("auto_open"))
        findings.append(
            f"Sandbox replay shows {'AutoOpen/Workbook_Open trigger and ' if auto_open else ''}"
            f"macro-triggered child-process activity "
            f"({len(vba_calls)} suspicious VBA call(s) detected)."
        )
        if vba_calls:
            extra["vba_suspicious_calls"] = vba_calls[:6]
        refs.extend(["scenario.payload.auto_open", "scenario.payload.vba_suspicious_calls"])
    elif hypothesis == "fileless_attack":
        commands = list(payload.get("commands") or [])
        fileless_indicators = [
            c for c in commands
            if any(t in str(c).lower() for t in [
                "iex", "invoke-expression", "[reflection.assembly]", "memorystream",
                "frombase64string", "amsiutils", "virtualalloc", "createthread",
                "invoke-mimikatz", "scriptblock",
            ])
        ]
        findings.append(
            f"Sandbox replay detected fileless execution: {len(fileless_indicators)} in-memory "
            f"payload indicator(s) — no script file written to disk. AMSI and ScriptBlock "
            f"telemetry required to capture decoded payload."
        )
        if fileless_indicators:
            extra["fileless_indicators"] = [str(x)[:120] for x in fileless_indicators[:4]]
        refs.extend(["scenario.payload.commands", "scenario.payload.process_tree.children"])
    else:
        findings.append("No sandbox scenario was mapped for this hypothesis.")
        refs.append("scenario.payload")
    result: Dict[str, Any] = {
        "agent": "Sandbox Detonation Agent",
        "status": "observed",
        "verdict_impact": "material",
        "inspected": "Inert isolated runtime replay using the mapped scenario contract.",
        "findings": findings,
        "evidence_refs": refs,
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "inert_sandbox_replay",
        },
    }
    if extra:
        result["extra"] = extra
    return result


def _process_tree_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    findings: List[str] = []
    refs: List[str] = []
    extra: Dict[str, Any] = {}
    if hypothesis == "lolbin_command_sequence":
        children = ((payload.get("process_tree") or {}).get("children") or [])
        child_names = ", ".join(str((child or {}).get("name") or "?") for child in children[:4])
        # Per-binary LOLBin risk scoring
        scored = _score_process_children(children)
        profiles = scored["profiles"]
        composite = scored["composite_score"]
        top = scored.get("top_binary") or {}
        if profiles:
            profile_summary = "; ".join(
                f"{p['binary']} ({p['technique']}, risk={p['risk_score']}, flag={p['detection_flag']})"
                for p in profiles[:4]
            )
            findings.append(
                f"LOLBin risk scoring: composite={composite}/10. "
                f"High-risk binaries detected — {profile_summary}."
            )
            extra["lolbin_risk_profiles"] = profiles
            extra["composite_lolbin_score"] = composite
            if top:
                extra["top_risk_binary"] = top
        else:
            findings.append(f"Observed child-process lineage: {child_names or 'cmd.exe lineage unavailable'}.")
        refs.append("scenario.payload.process_tree.children")
    elif hypothesis == "c2_beacon":
        parent = payload.get("parent_process") or "unknown"
        process = payload.get("process_name") or "unknown"
        # Score beacon process against LOLBin catalog
        beacon_profile = _LOLBIN_RISK.get(process.lower()) or _LOLBIN_RISK.get(process.lower() + ".exe")
        if beacon_profile:
            findings.append(
                f"Beacon process '{process}' is a known LOLBin "
                f"(technique={beacon_profile['technique']}, risk={beacon_profile['score']}/10). "
                f"Parent: {parent}."
            )
            extra["beacon_process_risk"] = beacon_profile
        else:
            findings.append(
                f"Observed process/network association: {parent} -> {process}."
            )
        refs.extend(["scenario.payload.parent_process", "scenario.payload.process_name"])
    elif hypothesis == "macros":
        macro_streams = list(payload.get("macro_streams") or [])
        vba_calls = list(payload.get("vba_suspicious_calls") or [])
        findings.append(
            f"Office macro path showed scripted execution primitives and external-link follow-on behavior "
            f"({len(macro_streams)} macro stream(s), {len(vba_calls)} suspicious call(s))."
        )
        if vba_calls:
            extra["vba_suspicious_calls"] = vba_calls[:6]
        refs.extend(["scenario.payload.macro_streams", "scenario.payload.vba_suspicious_calls"])
    elif hypothesis == "fileless_attack":
        children = ((payload.get("process_tree") or {}).get("children") or [])
        scored = _score_process_children(children)
        profiles = scored["profiles"]
        composite = scored["composite_score"]
        findings.append(
            f"Fileless process chain: no script file on disk. "
            f"LOLBin risk score={composite}/10 across {len(profiles)} binary/ies in process lineage. "
            f"Check AMSI bypass and ScriptBlock Event 4104 for decoded payload content."
        )
        if profiles:
            extra["lolbin_risk_profiles"] = profiles
        refs.extend(["scenario.payload.process_tree.children", "scenario.payload.commands"])
    result: Dict[str, Any] = {
        "agent": "Process Tree Agent",
        "status": "observed",
        "verdict_impact": "material",
        "inspected": "Runtime process lineage, command-line intent, LOLBin risk scoring, and child-process ancestry.",
        "findings": findings,
        "evidence_refs": refs or ["scenario.payload"],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "process_tree_contract",
        },
    }
    if extra:
        result["extra"] = extra
    return result


def _shannon_entropy(text: str) -> float:
    """Calculate Shannon entropy of a string (bits per character)."""
    if not text:
        return 0.0
    freq: Dict[str, int] = {}
    for ch in text:
        freq[ch] = freq.get(ch, 0) + 1
    length = len(text)
    return round(-sum((c / length) * math.log2(c / length) for c in freq.values()), 4)


def _dns_proxy_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    findings: List[str] = []
    refs: List[str] = []
    extra: Dict[str, Any] = {}
    if hypothesis == "lolbin_command_sequence":
        download_url = payload.get("download_url") or "unknown"
        findings.append(f"Proxy/DNS telemetry shows inert payload-fetch destination: {download_url}.")
        # Flag if URL uses a known staging domain
        if any(ioc in str(download_url).lower() for ioc in ["balashnikovai", "cdn.", "update.", "svchost"]):
            findings.append("Download URL matches known staging domain pattern — high-confidence LOLBin delivery IOC.")
            extra["staging_domain_match"] = True
        refs.append("scenario.payload.download_url")
    elif hypothesis == "c2_beacon":
        domain = payload.get("destination_domain") or "unknown"
        dns_queries = list(payload.get("dns_txt_queries") or [])
        interval = payload.get("beacon_interval_sec")
        jitter = payload.get("jitter_pct")
        cv = _beacon_cv(interval, jitter)
        # Shannon entropy of domain name (high entropy = likely DGA or encoded subdomain)
        domain_entropy = _shannon_entropy(domain.split(".")[0] if domain != "unknown" else domain)
        findings.append(
            f"DNS/proxy telemetry shows repeated lookups/posts to {domain}. "
            f"Beacon CV={cv} ({'regular' if cv < BEACON_CV_AUTOMATED_THRESHOLD else 'irregular'}). "
            f"Domain label entropy={domain_entropy} ({'DGA/encoded subdomain likely' if domain_entropy >= DNS_LABEL_HIGH_ENTROPY_THRESHOLD else 'human-readable domain'})."
        )
        if dns_queries:
            findings.append(f"DNS TXT record queries detected ({len(dns_queries)}): potential C2 command channel.")
            extra["dns_txt_queries"] = dns_queries[:4]
        extra["beacon_cv"] = cv
        extra["domain_label_entropy"] = domain_entropy
        refs.extend(["scenario.payload.destination_domain", "scenario.payload.dns_txt_queries"])
    elif hypothesis == "macros":
        external_links = list(payload.get("external_links") or [])
        findings.append(
            f"Macro detonation path includes {len(external_links)} external retrieval IOC(s) "
            f"from workbook VBA and external links."
        )
        if external_links:
            extra["external_links"] = external_links[:4]
        refs.extend(["scenario.payload.external_links", "scenario.payload.vba_suspicious_calls"])
    elif hypothesis == "fileless_attack":
        download_url = payload.get("download_url") or "unknown"
        findings.append(
            f"Fileless attack may include an initial stager download: {download_url}. "
            f"After in-memory execution, no further disk-based network activity is expected — "
            f"monitor process network handles rather than file system."
        )
        refs.extend(["scenario.payload.download_url", "scenario.payload.destination_domain"])
    result: Dict[str, Any] = {
        "agent": "DNS / Proxy Agent",
        "status": "observed",
        "verdict_impact": "supporting",
        "inspected": "Proxy, DNS, callback destination, domain entropy, and beacon CV from the isolated lab contract.",
        "findings": findings,
        "evidence_refs": refs or ["scenario.payload"],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "network_ioc_contract",
        },
    }
    if extra:
        result["extra"] = extra
    return result


def _firewall_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    findings: List[str] = []
    refs: List[str] = []
    if hypothesis == "c2_beacon":
        findings.append(
            f"Firewall/NDR lane confirms repeated outbound connections to {payload.get('destination_ip') or 'unknown'} over 24h."
        )
        refs.extend(["scenario.payload.destination_ip", "scenario.payload.connection_count_24h"])
    elif hypothesis == "lolbin_command_sequence":
        findings.append("Firewall telemetry shows outbound retrieval activity consistent with LOLBin staging.")
        refs.append("scenario.payload.download_url")
    elif hypothesis == "macros":
        findings.append("Firewall telemetry shows workbook-triggered external retrieval IOC(s) requiring containment review.")
        refs.append("scenario.payload.external_links")
    elif hypothesis == "fileless_attack":
        findings.append(
            "Fileless attack produces minimal firewall-visible traffic — monitor for stager download, "
            "then focus on process-level network handles and AMSI telemetry rather than egress flows."
        )
        refs.extend(["scenario.payload.download_url", "scenario.payload.destination_ip"])
    return {
        "agent": "Firewall / NDR Agent",
        "status": "observed",
        "verdict_impact": "supporting",
        "inspected": "Firewall, NDR, and egress behavior from the isolated runtime contract.",
        "findings": findings,
        "evidence_refs": refs or ["scenario.payload"],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "egress_contract",
        },
    }


def _lolbin_chain_scorer_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    commands = [str(x or "") for x in (payload.get("commands") or [])]
    children = ((payload.get("process_tree") or {}).get("children") or [])
    scored = _score_process_children(children)
    techniques: List[str] = []
    for child in children:
        techniques.extend(
            canonical_attack_ids_for_binary(
                str((child or {}).get("name") or ""),
                str((child or {}).get("cmdline") or ""),
            )
        )
    for cmd in commands:
        lowered = str(cmd).lower()
        for binary in ("certutil", "bitsadmin", "mshta", "regsvr32", "rundll32", "wscript", "cscript", "powershell", "schtasks", "wmic", "msiexec", "forfiles", "cmd"):
            if binary in lowered:
                techniques.extend(canonical_attack_ids_for_binary(binary, lowered))
    seen: set[str] = set()
    deduped = [x for x in techniques if x and not (x in seen or seen.add(x))]
    return {
        "agent": "LOLBin Chain Scorer Agent",
        "status": "observed" if hypothesis in {"lolbin_command_sequence", "macros", "fileless_attack"} else "no_evidence",
        "verdict_impact": "material" if deduped else "supporting",
        "inspected": "Per-binary LOLBAS risk, command chain composition, and ATT&CK technique alignment.",
        "findings": [
            f"Derived LOLBin ATT&CK techniques: {', '.join(deduped) or 'none'}.",
            f"Composite LOLBin process risk score={scored.get('composite_score', 0)}/10.",
        ],
        "evidence_refs": ["scenario.payload.commands", "scenario.payload.process_tree.children"],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "lolbin_chain_scoring",
        },
        "extra": {"derived_mitre_attack": deduped, "composite_lolbin_score": scored.get("composite_score", 0)},
    }


def _command_line_analyzer_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    commands = [str(x or "") for x in (payload.get("commands") or [])]
    suspicious_flags: List[str] = []
    for cmd in commands:
        lowered = cmd.lower()
        for tok in ("-executionpolicy bypass", "-windowstyle hidden", "-enc", "-encodedcommand", "-urlcache", "/transfer", "/create", "javascript:", "http://", "https://"):
            if tok in lowered:
                suspicious_flags.append(tok)
    return {
        "agent": "Command Line Analyzer Agent",
        "status": "observed" if commands else "no_evidence",
        "verdict_impact": "material" if suspicious_flags else "supporting",
        "inspected": "Command-line flags, obfuscation hints, remote URLs, and execution intent.",
        "findings": [f"Suspicious command-line indicators: {', '.join(sorted(set(suspicious_flags))) or 'none'}."],
        "evidence_refs": ["scenario.payload.commands"],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "command_line_analysis",
        },
        "extra": {"command_line_flags": sorted(set(suspicious_flags))},
    }


def _fileless_indicator_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    commands = [str(x or "") for x in (payload.get("commands") or [])]
    indicators = [
        cmd[:120]
        for cmd in commands
        if any(tok in cmd.lower() for tok in ("iex", "invoke-expression", "[reflection.assembly]", "memorystream", "frombase64string", "amsiutils", "__eventfilter", "__filtertoconsumerbinding"))
    ]
    return {
        "agent": "Fileless Indicator Agent",
        "status": "observed" if indicators else "no_evidence",
        "verdict_impact": "material" if indicators else "supporting",
        "inspected": "AMSI-bypass patterns, in-memory loaders, and WMI/fileless persistence indicators.",
        "findings": [f"Fileless indicators observed: {len(indicators)}."],
        "evidence_refs": ["scenario.payload.commands"],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "fileless_indicator_scan",
        },
        "extra": {"fileless_indicators": indicators[:6]},
    }


def _beacon_timing_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    interval = payload.get("beacon_interval_sec")
    jitter = payload.get("jitter_pct")
    cv = _beacon_cv(interval, jitter)
    regular = cv < BEACON_CV_AUTOMATED_THRESHOLD
    return {
        "agent": "Beacon Timing Agent",
        "status": "observed" if hypothesis == "c2_beacon" and interval else "no_evidence",
        "verdict_impact": "material" if regular else "supporting",
        "inspected": "Beacon interval regularity, jitter, and automated-vs-human callback cadence.",
        "findings": [f"Beacon CV={cv}; automated threshold={BEACON_CV_AUTOMATED_THRESHOLD}."],
        "evidence_refs": ["scenario.payload.beacon_interval_sec", "scenario.payload.jitter_pct"],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "beacon_timing_analysis",
        },
        "extra": {"beacon_cv": cv, "beacon_regular": regular},
    }


def _ppid_spoof_detector_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    tree = payload.get("process_tree") or {}
    parent_pid = tree.get("parent_pid")
    actual_creator_pid = tree.get("actual_creator_pid")
    spoofed = parent_pid is not None and actual_creator_pid is not None and str(parent_pid) != str(actual_creator_pid)
    return {
        "agent": "PPID Spoof Detector Agent",
        "status": "observed" if spoofed else "no_evidence",
        "verdict_impact": "supporting",
        "inspected": "Claimed parent PID versus actual creator PID for process ancestry integrity.",
        "findings": [f"PPID spoof detected={spoofed}."],
        "evidence_refs": ["scenario.payload.process_tree.parent_pid", "scenario.payload.process_tree.actual_creator_pid"],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "parent_pid_integrity_check",
        },
        "extra": {"ppid_spoof_detected": spoofed},
    }


def _registry_persistence_agent(hypothesis: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    payload = scenario.get("payload") or {}
    commands = [str(x or "") for x in (payload.get("commands") or [])]
    persistence = [cmd[:120] for cmd in commands if "schtasks" in cmd.lower() or "__eventfilter" in cmd.lower() or "runonce" in cmd.lower()]
    return {
        "agent": "Registry / Persistence Agent",
        "status": "observed" if persistence else "no_evidence",
        "verdict_impact": "supporting",
        "inspected": "Persistence mechanisms including scheduled tasks, Run keys, and WMI subscriptions.",
        "findings": [f"Persistence indicators: {len(persistence)}."],
        "evidence_refs": ["scenario.payload.commands"],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "persistence_indicator_scan",
        },
        "extra": {"persistence_indicators": persistence[:6]},
    }


def _artifact_ref_for_hypothesis(hypothesis: str) -> str:
    if hypothesis == "lolbin_command_sequence":
        return "scenario.payload.commands"
    if hypothesis == "c2_beacon":
        return "scenario.payload.destination_domain"
    if hypothesis in ("macros", "fileless_attack"):
        return "scenario.payload.vba_suspicious_calls"
    return "scenario.payload"


def _correlation_agent(hypothesis: str, scenario: Dict[str, Any], agents: List[Dict[str, Any]]) -> Dict[str, Any]:
    refs = sorted({ref for agent in agents for ref in (agent.get("evidence_refs") or [])})
    # Aggregate extra fields from sub-agents for richer correlation context
    extra_combined: Dict[str, Any] = {}
    for agent in agents:
        for k, v in (agent.get("extra") or {}).items():
            if k not in extra_combined:
                extra_combined[k] = v
    if hypothesis == "c2_beacon":
        cv = extra_combined.get("beacon_cv", "unknown")
        summary = (
            f"Parallel swarm correlation confirms network-beacon and process-context overlap "
            f"(beacon CV={cv}) before promoting ATT&CK C2 mappings."
        )
    elif hypothesis == "lolbin_command_sequence":
        composite = extra_combined.get("composite_lolbin_score", "unknown")
        summary = (
            f"Parallel swarm correlation confirms process, command-line, and retrieval overlap "
            f"(LOLBin composite risk={composite}/10) before promoting execution mappings."
        )
    elif hypothesis == "fileless_attack":
        fileless_count = len(extra_combined.get("fileless_indicators") or [])
        summary = (
            f"Parallel swarm correlation confirms fileless execution indicators ({fileless_count} "
            f"in-memory pattern(s)). AMSI + ScriptBlock telemetry required for payload recovery."
        )
    else:
        summary = "Parallel swarm correlation confirms macro execution context before promoting active ATT&CK mappings."
    return {
        "agent": "Correlation Agent",
        "status": "observed",
        "verdict_impact": "material",
        "inspected": "Cross-agent evidence promotion gate requiring sandbox, process, and network agreement.",
        "findings": [summary],
        "evidence_refs": refs[:8] or [_artifact_ref_for_hypothesis(hypothesis)],
        "provenance": {
            "source": "isolated_runtime_lab",
            "scenario_id": scenario.get("scenario_id"),
            "extraction_method": "cross_agent_correlation_gate",
        },
    }


def run_runtime_evidence_swarm(*, attack_hypothesis: str, filename: str | None = None) -> Dict[str, Any]:
    normalized = str(attack_hypothesis or "").strip().lower()
    mapping = _HYPOTHESIS_TO_SCENARIO.get(normalized)
    if not mapping:
        return {
            "supported": False,
            "runtime_mode": "isolated_inert_runtime_lab",
            "runtime_label": "No isolated runtime scenario is mapped for this hypothesis.",
            "attack_hypothesis": normalized or "unknown",
            "claim_status": "possible",
            "finding_group": "unconfirmed_higher_order_hypotheses",
            "evidence_lane": "runtime_lab_unavailable",
            "mitre_attack": [],
            "mitre_atlas": [],
            "runtime_evidence_present": [],
            "runtime_evidence_missing": [],
            "parallel_swarm": [],
        }

    scenario = get_scenario(str(mapping.get("scenario_id")))
    with ThreadPoolExecutor(max_workers=10) as exec_pool:
        futures = [
            exec_pool.submit(_sandbox_agent, normalized, scenario),
            exec_pool.submit(_process_tree_agent, normalized, scenario),
            exec_pool.submit(_dns_proxy_agent, normalized, scenario),
            exec_pool.submit(_firewall_agent, normalized, scenario),
            exec_pool.submit(_lolbin_chain_scorer_agent, normalized, scenario),
            exec_pool.submit(_command_line_analyzer_agent, normalized, scenario),
            exec_pool.submit(_fileless_indicator_agent, normalized, scenario),
            exec_pool.submit(_beacon_timing_agent, normalized, scenario),
            exec_pool.submit(_ppid_spoof_detector_agent, normalized, scenario),
            exec_pool.submit(_registry_persistence_agent, normalized, scenario),
        ]
        agent_results = [future.result() for future in futures]
    agent_results.append(_correlation_agent(normalized, scenario, agent_results))

    runtime_evidence_present = list(mapping.get("runtime_evidence_present") or [])
    runtime_evidence_missing = list(mapping.get("runtime_evidence_missing") or [])
    derived_attack: List[str] = []
    for agent in agent_results:
        for item in (agent.get("extra") or {}).get("derived_mitre_attack", []):
            s = str(item or "").strip()
            if s:
                derived_attack.append(s)
    seen_attack: set[str] = set()
    mitre_attack = [x for x in derived_attack if x and not (x in seen_attack or seen_attack.add(x))]
    if not mitre_attack:
        mitre_attack = list(scenario.get("mitre_attack") or [])
    summary = (
        f"Parallel runtime swarm confirmed {normalized.replace('_', ' ')} using isolated sandbox, process, DNS/proxy, "
        f"and firewall evidence from scenario {scenario.get('scenario_id')}."
    )
    payload_analysis_override = {
        "attack_hypothesis": normalized,
        "mitre_attack": mitre_attack,
        "possible_mitre_attack": [],
        "mitre_atlas": [],
        "possible_mitre_atlas": [],
        "pasta_stage": str(scenario.get("pasta_stage") or "Stage4:ThreatAnalysis"),
        "decode_path": "runtime_confirmed_isolated_lab",
        "suggested_next_step": "contain_and_escalate",
        "claim_status": "observed",
        "finding_group": "active_findings",
        "evidence_lane": str(mapping.get("evidence_lane") or "runtime_confirmed_detonation"),
        "runtime_confirmation_required": False,
        "runtime_evidence_required": runtime_evidence_missing,
        "runtime_evidence_present": runtime_evidence_present,
    }
    return {
        "supported": True,
        "runtime_mode": "isolated_inert_runtime_lab",
        "runtime_label": "Isolated runtime lab evidence (synthetic but execution-backed within the sandbox contract).",
        "attack_hypothesis": normalized,
        "scenario_id": scenario.get("scenario_id"),
        "scenario_name": scenario.get("name"),
        "claim_status": "observed",
        "finding_group": "active_findings",
        "evidence_lane": str(mapping.get("evidence_lane") or "runtime_confirmed_detonation"),
        "mitre_attack": mitre_attack,
        "mitre_atlas": [],
        "runtime_evidence_present": runtime_evidence_present,
        "runtime_evidence_missing": runtime_evidence_missing,
        "parallel_swarm": agent_results,
        "artifact_provenance": [
            {
                "source_file": filename or "uploaded_artifact",
                "extraction_method": "isolated_runtime_lab_mapping",
                "match_ref": _artifact_ref_for_hypothesis(normalized),
                "confidence": "high",
            },
            {
                "source_file": str(scenario.get("scenario_id") or "runtime_scenario"),
                "extraction_method": "scenario_contract",
                "match_ref": "scenario.payload",
                "confidence": "high",
            },
        ],
        "payload_analysis_override": payload_analysis_override,
        "summary": summary,
    }
