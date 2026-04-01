from __future__ import annotations

import re
from typing import Any, Dict, List

import requests

from src.app.security.security_event_ingest import ingest_security_event


def _parse_ts_from_syslog(line: str) -> str | None:
    # Supports ISO8601 in-line (preferred for determinism in tests)
    m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)", line)
    if m:
        return str(m.group(1))
    return None


def parse_firewall_syslog_line(line: str, *, tenant_id: str = "default", trace_id: str | None = None) -> Dict[str, Any]:
    raw = str(line or "").strip()
    kv = dict(re.findall(r"([A-Za-z0-9_.-]+)=([^\s]+)", raw))
    src = kv.get("src") or kv.get("src_ip") or kv.get("srcip")
    dst = kv.get("dst") or kv.get("dst_ip") or kv.get("dstip")
    action = (kv.get("action") or kv.get("act") or "").lower()
    sev = (kv.get("severity") or kv.get("sev") or "").lower()
    event_id = kv.get("event_id") or kv.get("id") or kv.get("msgid")
    if not event_id:
        event_id = f"fw-{abs(hash(raw)) % 10_000_000}"
    conf = 0.8 if action in {"deny", "drop", "blocked", "block"} else 0.55
    if sev in {"critical"}:
        conf = max(conf, 0.95)
    elif sev in {"high"}:
        conf = max(conf, 0.8)
    return {
        "event_id": event_id,
        "trace_id": trace_id or kv.get("trace_id") or kv.get("correlation_id"),
        "tenant_id": tenant_id,
        "timestamp": _parse_ts_from_syslog(raw),
        "event_time": _parse_ts_from_syslog(raw),
        "severity": sev or ("high" if action in {"deny", "drop", "blocked", "block"} else "medium"),
        "confidence": conf,
        "event_type": "network",
        "type": "network",
        "src_ip": src,
        "dst_ip": dst,
        "device_id": kv.get("device") or kv.get("host"),
        "action": action or "observe",
        "raw_syslog": raw,
    }


def ingest_firewall_syslog_lines(
    *,
    lines: List[str],
    tenant_id: str = "default",
    trace_id: str | None = None,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for line in lines or []:
        evt = parse_firewall_syslog_line(str(line or ""), tenant_id=tenant_id, trace_id=trace_id)
        results.append(ingest_security_event(vendor="firewall", payload=evt))
    return {
        "ok": True,
        "vendor": "firewall",
        "ingested": len(results),
        "results": results,
    }


def parse_process_tree_event(
    payload: Dict[str, Any],
    *,
    tenant_id: str = "default",
    trace_id: str | None = None,
) -> Dict[str, Any]:
    data = dict(payload or {})
    process_name = str(data.get("process_name") or data.get("name") or "").strip()
    parent_process = str(data.get("parent_process") or data.get("parent_name") or "").strip()
    command_line = str(data.get("command_line") or data.get("cmdline") or "").strip()
    event_id = str(data.get("event_id") or data.get("id") or f"proc-{abs(hash((process_name, command_line, parent_process))) % 10_000_000}")
    lowered = " ".join([process_name.lower(), parent_process.lower(), command_line.lower()])
    confidence = 0.55
    if any(tok in lowered for tok in ("powershell", "mshta", "regsvr32", "rundll32", "certutil", "wscript", "cscript")):
        confidence = 0.85
    return {
        "event_id": event_id,
        "trace_id": trace_id or str(data.get("trace_id") or "").strip() or None,
        "tenant_id": tenant_id,
        "timestamp": str(data.get("timestamp") or data.get("event_time") or ""),
        "event_time": str(data.get("event_time") or data.get("timestamp") or ""),
        "severity": str(data.get("severity") or ("high" if confidence >= 0.8 else "medium")).lower(),
        "confidence": confidence,
        "event_type": "other",
        "type": "other",
        "device_id": data.get("device_id"),
        "user_id": data.get("user_id"),
        "process_name": process_name,
        "parent_process": parent_process,
        "command_line": command_line,
        "raw": data,
    }


def ingest_process_tree_events(
    *,
    events: List[Dict[str, Any]],
    tenant_id: str = "default",
    trace_id: str | None = None,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for event in events or []:
        evt = parse_process_tree_event(event or {}, tenant_id=tenant_id, trace_id=trace_id)
        results.append(ingest_security_event(vendor="process_tree", payload=evt))
    return {
        "ok": True,
        "vendor": "process_tree",
        "ingested": len(results),
        "results": results,
    }


def parse_edr_memory_event(
    payload: Dict[str, Any],
    *,
    tenant_id: str = "default",
    trace_id: str | None = None,
) -> Dict[str, Any]:
    data = dict(payload or {})
    event_id = str(data.get("event_id") or data.get("id") or f"edrmem-{abs(hash(str(sorted(data.items())))) % 10_000_000}")
    process_name = str(data.get("process_name") or data.get("name") or "").strip()
    detection = str(data.get("detection_name") or data.get("detection") or "").strip()
    lowered = " ".join(
        [
            process_name.lower(),
            detection.lower(),
            str(data.get("memory_strings") or "").lower(),
            str(data.get("module") or "").lower(),
        ]
    )
    confidence = 0.6
    if any(tok in lowered for tok in ("amsi", "scriptblock", "createremotethread", "processtampering", "hollow", "reflective", "shellcode", "virtualalloc")):
        confidence = 0.9
    return {
        "event_id": event_id,
        "trace_id": trace_id or str(data.get("trace_id") or "").strip() or None,
        "tenant_id": tenant_id,
        "timestamp": str(data.get("timestamp") or data.get("event_time") or ""),
        "event_time": str(data.get("event_time") or data.get("timestamp") or ""),
        "severity": str(data.get("severity") or ("high" if confidence >= 0.85 else "medium")).lower(),
        "confidence": confidence,
        "event_type": "other",
        "type": "other",
        "device_id": data.get("device_id"),
        "user_id": data.get("user_id"),
        "process_name": process_name,
        "detection_name": detection,
        "raw": data,
    }


def ingest_edr_memory_events(
    *,
    events: List[Dict[str, Any]],
    tenant_id: str = "default",
    trace_id: str | None = None,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for event in events or []:
        evt = parse_edr_memory_event(event or {}, tenant_id=tenant_id, trace_id=trace_id)
        results.append(ingest_security_event(vendor="edr_memory", payload=evt))
    return {
        "ok": True,
        "vendor": "edr_memory",
        "ingested": len(results),
        "results": results,
    }


def parse_dns_proxy_line(line: str, *, tenant_id: str = "default", trace_id: str | None = None) -> Dict[str, Any]:
    raw = str(line or "").strip()
    kv = dict(re.findall(r"([A-Za-z0-9_.-]+)=([^\s]+)", raw))
    event_id = kv.get("event_id") or kv.get("id") or f"dns-{abs(hash(raw)) % 10_000_000}"
    domain = kv.get("domain") or kv.get("host") or kv.get("query") or kv.get("dst_host")
    dst = kv.get("dst") or kv.get("dst_ip") or kv.get("dstip")
    action = str(kv.get("action") or kv.get("act") or "observe").lower()
    severity = str(kv.get("severity") or kv.get("sev") or "medium").lower()
    confidence = 0.75 if domain or dst else 0.5
    return {
        "event_id": event_id,
        "trace_id": trace_id or kv.get("trace_id") or kv.get("correlation_id"),
        "tenant_id": tenant_id,
        "timestamp": _parse_ts_from_syslog(raw),
        "event_time": _parse_ts_from_syslog(raw),
        "severity": severity,
        "confidence": confidence,
        "event_type": "network",
        "type": "network",
        "src_ip": kv.get("src") or kv.get("src_ip") or kv.get("srcip"),
        "dst_ip": dst,
        "dst_host": domain,
        "action": action,
        "device_id": kv.get("device") or kv.get("host"),
        "raw_syslog": raw,
    }


def ingest_dns_proxy_lines(
    *,
    lines: List[str],
    tenant_id: str = "default",
    trace_id: str | None = None,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for line in lines or []:
        evt = parse_dns_proxy_line(str(line or ""), tenant_id=tenant_id, trace_id=trace_id)
        results.append(ingest_security_event(vendor="dns_proxy", payload=evt))
    return {
        "ok": True,
        "vendor": "dns_proxy",
        "ingested": len(results),
        "results": results,
    }


def pull_crowdstrike_and_ingest(
    *,
    tenant_id: str = "default",
    trace_id: str | None = None,
    limit: int = 50,
    lookback_minutes: int = 60,
    base_url: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    timeout_seconds: int = 15,
) -> Dict[str, Any]:
    import os
    from datetime import datetime, timedelta, timezone

    api_base = str(base_url or os.getenv("CROWDSTRIKE_API_URL", "https://api.crowdstrike.com")).rstrip("/")
    cid = str(client_id or os.getenv("CROWDSTRIKE_CLIENT_ID", "")).strip()
    csec = str(client_secret or os.getenv("CROWDSTRIKE_CLIENT_SECRET", "")).strip()
    if not cid or not csec:
        return {"ok": False, "reason": "crowdstrike_credentials_missing", "ingested": 0, "results": []}

    token_r = requests.post(
        f"{api_base}/oauth2/token",
        data={"client_id": cid, "client_secret": csec},
        timeout=timeout_seconds,
    )
    if token_r.status_code >= 300:
        return {"ok": False, "reason": f"crowdstrike_oauth_failed_{token_r.status_code}", "ingested": 0, "results": []}
    token = str((token_r.json() or {}).get("access_token") or "").strip()
    if not token:
        return {"ok": False, "reason": "crowdstrike_oauth_missing_token", "ingested": 0, "results": []}

    since = (datetime.now(timezone.utc) - timedelta(minutes=max(1, int(lookback_minutes)))).isoformat()
    headers = {"Authorization": f"Bearer {token}"}
    detections_r = requests.get(
        f"{api_base}/detects/queries/detects/v1",
        params={"limit": max(1, min(int(limit), 500)), "filter": f"created_timestamp:>='{since}'"},
        headers=headers,
        timeout=timeout_seconds,
    )
    if detections_r.status_code >= 300:
        return {"ok": False, "reason": f"crowdstrike_detect_query_failed_{detections_r.status_code}", "ingested": 0, "results": []}
    ids = list((detections_r.json() or {}).get("resources") or [])
    if not ids:
        return {"ok": True, "ingested": 0, "results": [], "source_count": 0}

    detail_r = requests.get(
        f"{api_base}/detects/entities/summaries/GET/v1",
        params=[("ids", str(i)) for i in ids[: max(1, min(len(ids), int(limit)))]],
        headers=headers,
        timeout=timeout_seconds,
    )
    if detail_r.status_code >= 300:
        return {"ok": False, "reason": f"crowdstrike_detect_detail_failed_{detail_r.status_code}", "ingested": 0, "results": []}
    resources = list((detail_r.json() or {}).get("resources") or [])

    out: List[Dict[str, Any]] = []
    for r in resources:
        payload = {
            "detection_id": r.get("detection_id") or r.get("id"),
            "event_id": r.get("id") or r.get("detection_id"),
            "trace_id": trace_id or r.get("trace_id") or r.get("cid"),
            "tenant_id": tenant_id,
            "event_time": r.get("created_timestamp") or r.get("updated_timestamp"),
            "severity": str(r.get("severity") or "medium").lower(),
            "confidence": (float(r.get("confidence") or 0.8) if str(r.get("confidence") or "").strip() else 0.8),
            "event_type": "network",
            "src_ip": r.get("local_ip"),
            "dst_ip": r.get("external_ip"),
            "device_id": r.get("device_id"),
            "user_id": r.get("user_name"),
            "raw": r,
        }
        out.append(ingest_security_event(vendor="crowdstrike", payload=payload))
    return {"ok": True, "ingested": len(out), "results": out, "source_count": len(resources)}
