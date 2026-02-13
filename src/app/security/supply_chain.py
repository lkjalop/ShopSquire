from __future__ import annotations

import json
import os
import re
import ssl
import tempfile
import time
from typing import Any, Dict, Iterable, Tuple

import httpx

from src.app.deps import get_redis
from src.app.security.agent_events import (
    AgentInteractionType,
    ThreatCategory,
    log_agent_security_event,
)


def _load_baselines() -> Dict[str, Dict[str, Any]]:
    path = os.getenv("SUPPLY_CHAIN_BASELINES_PATH", "config/security/supply_chain_baselines.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _extract_paths(obj: Any, prefix: str = "") -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            yield path
            yield from _extract_paths(v, path)
    elif isinstance(obj, list) and obj:
        yield from _extract_paths(obj[0], f"{prefix}[]")


def _field_types(obj: Any, prefix: str = "") -> Dict[str, str]:
    types: Dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            types[path] = type(v).__name__
            types.update(_field_types(v, path))
    elif isinstance(obj, list) and obj:
        types.update(_field_types(obj[0], f"{prefix}[]"))
    return types


def _suspicious_markers(payload: str) -> list[str]:
    markers = []
    checks = [
        ("script_tag", r"<script"),
        ("eval_call", r"eval\s*\("),
        ("data_uri", r"data:text/html"),
        ("base64_exe", r"TVqQAAMAAAAEAAAA"),
    ]
    for name, pat in checks:
        if re.search(pat, payload, re.IGNORECASE):
            markers.append(name)
    return markers


def _cert_issuer(host: str) -> str | None:
    try:
        pem = ssl.get_server_certificate((host, 443))
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as tmp:
            tmp.write(pem.encode("utf-8"))
            tmp.flush()
            decoded = ssl._ssl._test_decode_cert(tmp.name)
        issuer = decoded.get("issuer") or []
        parts = []
        for item in issuer:
            for k, v in item:
                parts.append(f"{k}={v}")
        return ", ".join(parts) if parts else None
    except Exception:
        return None


class SupplyChainMonitor:
    def __init__(self):
        self.baselines = _load_baselines()
        self.enabled = str(os.getenv("SUPPLY_CHAIN_ENABLED", "true")).lower() not in ("0", "false", "no")
        self.ttl_seconds = int(os.getenv("SUPPLY_CHAIN_CHECK_TTL", "3600"))
        self.status_ttl = int(os.getenv("SUPPLY_CHAIN_STATUS_TTL", "86400"))
        self.redis = get_redis()

    def _cache_hit(self, key: str) -> bool:
        try:
            return bool(self.redis.get(key))
        except Exception:
            return False

    def _set_cache(self, key: str, ttl: int) -> None:
        try:
            self.redis.setex(key, ttl, "1")
        except Exception:
            pass

    def check_endpoint_integrity(self, vendor: str) -> None:
        if not self.enabled:
            return
        cfg = self.baselines.get(vendor) or {}
        endpoint = cfg.get("endpoint")
        if not endpoint:
            return
        cache_key = f"supplychain:check:{vendor}:{endpoint}"
        if self._cache_hit(cache_key):
            return
        issues = []
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.head(f"https://{endpoint}")
                if resp.status_code >= 400:
                    issues.append(f"status_{resp.status_code}")
                expected = [h.lower() for h in (cfg.get("expected_headers") or [])]
                headers = [h.lower() for h in resp.headers.keys()]
                missing = [h for h in expected if h not in headers]
                if missing:
                    issues.append(f"missing_headers:{','.join(missing)}")
        except Exception as exc:
            issues.append(f"connection_error:{type(exc).__name__}")

        expected_issuer = cfg.get("expected_issuer")
        if expected_issuer:
            issuer = _cert_issuer(endpoint)
            if not issuer or expected_issuer.lower() not in issuer.lower():
                issues.append("issuer_mismatch")

        status = "ok" if not issues else "warn"
        if issues:
            log_agent_security_event(
                interaction_type=AgentInteractionType.saas_api_call,
                source="shopsquire",
                destination=endpoint,
                threat_category=ThreatCategory.supply_chain,
                severity="warn",
                confidence=0.6,
                details={"vendor": vendor, "issues": issues},
                requires_escalation=False,
            )
        try:
            status_key = f"supplychain:status:{vendor}"
            self.redis.setex(
                status_key,
                self.status_ttl,
                json.dumps({"status": status, "issues": issues, "checked_at": time.time()}),
            )
        except Exception:
            pass
        self._set_cache(cache_key, self.ttl_seconds)

    def detect_response_anomaly(self, vendor: str, response_body: Dict[str, Any]) -> Tuple[bool, list[str]]:
        if not self.enabled:
            return False, []
        cfg = self.baselines.get(vendor) or {}
        endpoint = cfg.get("endpoint") or vendor
        baseline_key = f"supplychain:baseline:{vendor}:{endpoint}"
        payload = json.dumps(response_body or {}, ensure_ascii=False)
        current_fields = set(_extract_paths(response_body or {}))
        current_types = _field_types(response_body or {})
        suspicious = _suspicious_markers(payload)
        try:
            baseline_raw = self.redis.get(baseline_key)
        except Exception:
            baseline_raw = None
        if not baseline_raw:
            try:
                self.redis.setex(
                    baseline_key,
                    int(os.getenv("SUPPLY_CHAIN_BASELINE_TTL", "604800")),
                    json.dumps({"fields": sorted(list(current_fields)), "types": current_types, "sample_count": 1}),
                )
            except Exception:
                pass
            return False, []
        try:
            baseline = json.loads(baseline_raw)
        except Exception:
            baseline = {}
        baseline_fields = set(baseline.get("fields") or [])
        baseline_types = baseline.get("types") or {}
        anomalies = []
        new_fields = current_fields - baseline_fields
        missing_fields = baseline_fields - current_fields
        if new_fields:
            anomalies.append(f"new_fields:{len(new_fields)}")
        if missing_fields:
            anomalies.append(f"missing_fields:{len(missing_fields)}")
        type_changes = []
        for field, expected_type in baseline_types.items():
            cur = current_types.get(field)
            if cur and expected_type and cur != expected_type:
                type_changes.append(f"{field}:{expected_type}->{cur}")
        if type_changes:
            anomalies.append(f"type_changes:{len(type_changes)}")
        if suspicious:
            anomalies.append(f"suspicious:{','.join(suspicious)}")

        if anomalies:
            log_agent_security_event(
                interaction_type=AgentInteractionType.saas_api_call,
                source="shopsquire",
                destination=endpoint,
                threat_category=ThreatCategory.supply_chain,
                severity="warn",
                confidence=0.5,
                details={"vendor": vendor, "anomalies": anomalies},
                requires_escalation=False,
            )
            return True, anomalies
        try:
            baseline["fields"] = sorted(list(set(baseline_fields | current_fields)))
            baseline["types"] = {**baseline_types, **current_types}
            baseline["sample_count"] = int(baseline.get("sample_count") or 1) + 1
            self.redis.setex(
                baseline_key,
                int(os.getenv("SUPPLY_CHAIN_BASELINE_TTL", "604800")),
                json.dumps(baseline),
            )
        except Exception:
            pass
        return False, []

    def status_snapshot(self) -> Dict[str, Dict[str, Any]]:
        snapshot: Dict[str, Dict[str, Any]] = {}
        for vendor, cfg in (self.baselines or {}).items():
            endpoint = cfg.get("endpoint") or vendor
            entry = {"vendor": vendor, "endpoint": endpoint, "status": "unknown", "issues": [], "checked_at": None}
            try:
                raw = self.redis.get(f"supplychain:status:{vendor}")
                if raw:
                    data = json.loads(raw)
                    entry.update({
                        "status": data.get("status", "unknown"),
                        "issues": data.get("issues") or [],
                        "checked_at": data.get("checked_at"),
                    })
            except Exception:
                pass
            snapshot[vendor] = entry
        return snapshot
