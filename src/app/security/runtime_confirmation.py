from __future__ import annotations

import os
from typing import Any, Dict, List

from src.app.security.email_enrichment import detonate_targets
from src.app.security.lolbin_behavioral_catalog import canonical_attack_ids_for_binary
from src.app.security.vendor_connectors import parse_dns_proxy_line, parse_firewall_syslog_line, parse_process_tree_event
from src.app.security.runtime_evidence_lab import run_runtime_evidence_swarm


_ACTIVE_ATTACK: Dict[str, List[str]] = {
    "lolbin_command_sequence": ["T1105", "T1059.001", "T1197", "T1053.005", "T1218.005", "T1218.010", "T1218.011", "T1059.005", "T1140"],
    "c2_beacon": ["T1071.001", "T1071.004", "T1105", "T1573.002", "T1041"],
    "macros": ["T1566.001", "T1204.002", "T1059.001", "T1059.005"],
}


def _derive_runtime_attack_ids(hypothesis: str, process_events: List[Dict[str, Any]]) -> List[str]:
    if hypothesis != "lolbin_command_sequence":
        return list(_ACTIVE_ATTACK.get(hypothesis, []))
    attacks: List[str] = []
    for event in process_events:
        attacks.extend(
            canonical_attack_ids_for_binary(
                str(event.get("process_name") or ""),
                str(event.get("command_line") or ""),
            )
        )
    seen: set[str] = set()
    out = [x for x in attacks if x and not (x in seen or seen.add(x))]
    return out or list(_ACTIVE_ATTACK.get(hypothesis, []))


def _process_tree_present(hypothesis: str, events: List[Dict[str, Any]]) -> bool:
    for event in events:
        lowered = " ".join(
            [
                str(event.get("process_name") or "").lower(),
                str(event.get("parent_process") or "").lower(),
                str(event.get("command_line") or "").lower(),
            ]
        )
        if hypothesis == "lolbin_command_sequence" and any(tok in lowered for tok in ("powershell", "mshta", "regsvr32", "rundll32", "certutil")):
            return True
        if hypothesis == "macros" and any(tok in lowered for tok in ("excel", "winword", "powerpnt", "wscript.shell", "autoopen", "workbook_open")):
            return True
        if hypothesis == "c2_beacon" and any(tok in lowered for tok in ("powershell", "svchost", "beacon", "callback")):
            return True
        if hypothesis == "fileless_attack" and any(tok in lowered for tok in ("powershell", "wmi", "rundll32", "regsvr32", "mshta", "virtualalloc", "createremotethread")):
            return True
    return False


def _network_present(hypothesis: str, dns_proxy_events: List[Dict[str, Any]], firewall_events: List[Dict[str, Any]]) -> bool:
    if hypothesis == "lolbin_command_sequence":
        toks = ("http", "https", "download", "payload")
    elif hypothesis == "macros":
        toks = ("http", "https", "macro", "stage2", "payload")
    else:
        toks = ("c2", "beacon", "callback", "dns", "txt")
    for event in dns_proxy_events + firewall_events:
        lowered = " ".join(
            [
                str(event.get("dst_host") or "").lower(),
                str(event.get("dst_ip") or "").lower(),
                str(event.get("raw_syslog") or "").lower(),
            ]
        )
        if any(tok in lowered for tok in toks):
            return True
    return False


def _memory_present(events: List[Dict[str, Any]]) -> bool:
    for event in events:
        lowered = " ".join(
            [
                str(event.get("process_name") or "").lower(),
                str(event.get("detection_name") or "").lower(),
                str(event.get("raw") or "").lower(),
            ]
        )
        if any(tok in lowered for tok in ("amsi", "scriptblock", "createremotethread", "processtampering", "hollow", "reflective", "shellcode", "virtualalloc")):
            return True
    return False


def confirm_runtime_evidence(
    *,
    attack_hypothesis: str,
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    normalized = str(attack_hypothesis or "").strip().lower()
    ctx = dict(context or {})
    urls = [str(x) for x in (ctx.get("urls") or []) if str(x).strip()]
    attachment_hashes = [str(x) for x in (ctx.get("attachment_hashes") or []) if str(x).strip()]

    detonation = detonate_targets(urls, attachment_hashes)
    provider = str((detonation or {}).get("provider") or "")
    production_sandbox = provider == "private_sandbox"
    detonation_malicious = bool((detonation or {}).get("malicious"))

    process_events = [
        parse_process_tree_event(event or {}, tenant_id=str(ctx.get("tenant_id") or "default"), trace_id=str(ctx.get("trace_id") or "") or None)
        for event in (ctx.get("process_tree_events") or [])
        if isinstance(event, dict)
    ]
    dns_proxy_events = [
        parse_dns_proxy_line(str(line or ""), tenant_id=str(ctx.get("tenant_id") or "default"), trace_id=str(ctx.get("trace_id") or "") or None)
        for line in (ctx.get("dns_proxy_lines") or [])
        if str(line or "").strip()
    ]
    firewall_events = [
        parse_firewall_syslog_line(str(line or ""), tenant_id=str(ctx.get("tenant_id") or "default"), trace_id=str(ctx.get("trace_id") or "") or None)
        for line in (ctx.get("firewall_syslog_lines") or [])
        if str(line or "").strip()
    ]
    memory_events = [dict(event or {}) for event in (ctx.get("edr_memory_events") or []) if isinstance(event, dict)]

    process_ok = _process_tree_present(normalized, process_events)
    network_ok = _network_present(normalized, dns_proxy_events, firewall_events)
    memory_ok = _memory_present(memory_events)

    runtime_evidence_present: List[str] = []
    runtime_evidence_missing: List[str] = []

    if production_sandbox and detonation_malicious:
        runtime_evidence_present.append("sandbox_detonation: provider confirmed malicious runtime behavior")
    else:
        runtime_evidence_missing.append("sandbox_detonation: real provider confirmation required")
    if process_ok:
        runtime_evidence_present.append("endpoint_process_tree: runtime process lineage confirmed")
    else:
        runtime_evidence_missing.append("endpoint_process_tree: runtime process lineage required")
    if normalized == "fileless_attack":
        if memory_ok:
            runtime_evidence_present.append("edr_memory_forensics: runtime memory or process-tampering evidence confirmed")
        else:
            runtime_evidence_missing.append("edr_memory_forensics: runtime memory/process-tampering evidence required")
    if network_ok:
        runtime_evidence_present.append("dns_proxy_firewall_logs: runtime network overlap confirmed")
    elif normalized != "fileless_attack":
        runtime_evidence_missing.append("dns_proxy_firewall_logs: runtime DNS/proxy/firewall evidence required")

    production_confirmed = production_sandbox and detonation_malicious and process_ok and (memory_ok if normalized == "fileless_attack" else network_ok)
    confirmed_attack_ids = _derive_runtime_attack_ids(normalized, process_events)

    if production_confirmed:
        parallel_swarm = [
            {
                "agent": "Sandbox Provider Agent",
                "status": "observed",
                "verdict_impact": "material",
                "inspected": f"Private sandbox provider result from {provider}.",
                "findings": [f"Sandbox verdict malicious={detonation_malicious} score={detonation.get('score')}"],
                "evidence_refs": ["context.urls", "context.attachment_hashes"],
            },
            {
                "agent": "Process Tree Agent",
                "status": "observed",
                "verdict_impact": "material",
                "inspected": "Real ingested process-tree telemetry.",
                "findings": [f"Process telemetry events matched: {len(process_events)}"],
                "evidence_refs": ["context.process_tree_events"],
            },
            {
                "agent": "DNS / Proxy / Firewall Agent",
                "status": "observed",
                "verdict_impact": "material",
                "inspected": "Real DNS, proxy, and firewall log lines.",
                "findings": [f"DNS/proxy lines={len(dns_proxy_events)} firewall lines={len(firewall_events)}"],
                "evidence_refs": ["context.dns_proxy_lines", "context.firewall_syslog_lines"],
            },
        ]
        artifact_provenance = [
            {"source_file": "runtime_context", "extraction_method": "private_sandbox", "match_ref": "context.urls", "confidence": "high"},
            {"source_file": "runtime_context", "extraction_method": "process_tree_ingest", "match_ref": "context.process_tree_events", "confidence": "high"},
            {"source_file": "runtime_context", "extraction_method": "network_log_ingest", "match_ref": "context.dns_proxy_lines", "confidence": "high"},
        ]
        if normalized == "fileless_attack" and memory_ok:
            parallel_swarm.append(
                {
                    "agent": "EDR Memory Agent",
                    "status": "observed",
                    "verdict_impact": "material",
                    "inspected": "Real EDR memory or process-tampering telemetry.",
                    "findings": [f"Memory/process-tampering events matched: {len(memory_events)}"],
                    "evidence_refs": ["context.edr_memory_events"],
                }
            )
            artifact_provenance.append(
                {"source_file": "runtime_context", "extraction_method": "edr_memory_ingest", "match_ref": "context.edr_memory_events", "confidence": "high"}
            )
        return {
            "supported": True,
            "confirmation_tier": "production_confirmed",
            "runtime_mode": "provider_backed_runtime_confirmation",
            "runtime_label": "Production-confirmed via private sandbox provider and real process/network telemetry.",
            "attack_hypothesis": normalized,
            "claim_status": "observed",
            "finding_group": "active_findings",
            "evidence_lane": "production_confirmed_runtime_evidence",
            "mitre_attack": confirmed_attack_ids,
            "mitre_atlas": [],
            "runtime_evidence_present": runtime_evidence_present,
            "runtime_evidence_missing": runtime_evidence_missing,
            "parallel_swarm": parallel_swarm,
            "artifact_provenance": artifact_provenance,
            "payload_analysis_override": {
                "attack_hypothesis": normalized,
                "mitre_attack": confirmed_attack_ids,
                "possible_mitre_attack": [],
                "mitre_atlas": [],
                "possible_mitre_atlas": [],
                "decode_path": "production_confirmed_runtime_evidence",
                "suggested_next_step": "contain_and_escalate",
                "claim_status": "observed",
                "finding_group": "active_findings",
                "evidence_lane": "production_confirmed_runtime_evidence",
                "runtime_confirmation_required": False,
                "runtime_evidence_required": runtime_evidence_missing,
                "runtime_evidence_present": runtime_evidence_present,
            },
            "summary": f"Production-confirmed {normalized.replace('_', ' ')} via sandbox provider and real telemetry.",
        }

    if str(os.getenv("VISION_RUNTIME_LAB_FALLBACK", "0")).strip().lower() in ("1", "true", "yes", "on"):
        lab = run_runtime_evidence_swarm(attack_hypothesis=normalized, filename=str(ctx.get("filename") or "uploaded_artifact"))
        if isinstance(lab, dict) and lab.get("supported"):
            lab["confirmation_tier"] = "lab_confirmed"
            return lab

    return {
        "supported": normalized in _ACTIVE_ATTACK,
        "confirmation_tier": "pending_runtime_evidence",
        "runtime_mode": "provider_backed_runtime_confirmation",
        "runtime_label": "Pending real provider-backed runtime evidence. Active execution/C2 mappings remain disabled.",
        "attack_hypothesis": normalized,
        "claim_status": "possible",
        "finding_group": "unconfirmed_higher_order_hypotheses",
        "evidence_lane": "pending_runtime_confirmation",
        "mitre_attack": [],
        "mitre_atlas": [],
        "runtime_evidence_present": runtime_evidence_present,
        "runtime_evidence_missing": runtime_evidence_missing,
        "parallel_swarm": [
            {
                "agent": "Runtime Gate",
                "status": "pending",
                "verdict_impact": "material",
                "inspected": "Production confirmation gate requires sandbox provider, process tree, and runtime telemetry appropriate to the hypothesis.",
                "findings": runtime_evidence_missing,
                "evidence_refs": ["context.urls", "context.process_tree_events", "context.dns_proxy_lines", "context.firewall_syslog_lines", "context.edr_memory_events"],
            }
        ],
        "artifact_provenance": [],
        "payload_analysis_override": {
            "attack_hypothesis": normalized,
            "mitre_attack": [],
            "possible_mitre_attack": _derive_runtime_attack_ids(normalized, process_events),
            "mitre_atlas": [],
            "possible_mitre_atlas": [],
            "decode_path": "pending_runtime_confirmation",
            "suggested_next_step": "queue_sandbox_detonation",
            "claim_status": "possible",
            "finding_group": "unconfirmed_higher_order_hypotheses",
            "evidence_lane": "pending_runtime_confirmation",
            "runtime_confirmation_required": True,
            "runtime_evidence_required": runtime_evidence_missing,
            "runtime_evidence_present": runtime_evidence_present,
        },
        "summary": f"Runtime confirmation pending for {normalized.replace('_', ' ')}. No production ATT&CK promotion yet.",
    }
