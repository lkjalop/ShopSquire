from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Tuple
from urllib.request import Request, urlopen

from sqlalchemy import text

from src.app.models.db import db_session, upsert


REQUIRED_HEADERS = [
    "content-security-policy",
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
    "cross-origin-opener-policy",
    "cross-origin-embedder-policy",
    "cross-origin-resource-policy",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_csv_env(key: str) -> list[str]:
    raw = str(os.getenv(key, "") or "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def ensure_fingerprint_tables() -> None:
    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS security_fingerprint_scans (
                  id TEXT PRIMARY KEY,
                  scan_type TEXT NOT NULL,
                  target TEXT NOT NULL,
                  status TEXT NOT NULL,
                  fingerprint TEXT,
                  observed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  details_json TEXT
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS security_fingerprint_baselines (
                  scan_type TEXT NOT NULL,
                  target TEXT NOT NULL,
                  baseline_fingerprint TEXT,
                  baseline_json TEXT,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (scan_type, target)
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS security_fingerprint_alerts (
                  id TEXT PRIMARY KEY,
                  alert_type TEXT NOT NULL,
                  severity TEXT NOT NULL,
                  target TEXT NOT NULL,
                  scan_type TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  expected_fingerprint TEXT,
                  observed_fingerprint TEXT,
                  status TEXT NOT NULL DEFAULT 'open',
                  note TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  details_json TEXT
                )
                """
            )
        )
        db.commit()


def _scan_http_headers(url: str, timeout: float = 10.0) -> Dict[str, Any]:
    req = Request(url, headers={"User-Agent": "ShopSquireFingerprint/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        headers = {k.lower(): v for k, v in resp.getheaders()}
        missing = [h for h in REQUIRED_HEADERS if h not in headers]
        present = {k: headers[k] for k in headers if k in REQUIRED_HEADERS}
        set_cookie = headers.get("set-cookie")
        cookie_flags = {}
        if set_cookie:
            low = set_cookie.lower()
            cookie_flags = {
                "secure": "secure" in low,
                "httponly": "httponly" in low,
                "samesite": (
                    "none"
                    if "samesite=none" in low
                    else ("lax" if "samesite=lax" in low else ("strict" if "samesite=strict" in low else None))
                ),
            }
        digest = hashlib.sha256(json.dumps({"present": present, "missing": missing}, sort_keys=True).encode("utf-8")).hexdigest()
        return {
            "scan_type": "headers",
            "target": url,
            "status": "ok",
            "fingerprint": digest,
            "details": {"present": present, "missing": missing, "cookie_flags": cookie_flags},
        }


def _scan_tls(target: str, timeout: float = 10.0) -> Dict[str, Any]:
    host = target
    port = 443
    if ":" in target:
        h, p = target.rsplit(":", 1)
        host, port = h, int(p)
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            der = ssock.getpeercert(binary_form=True)
            cert = ssock.getpeercert()
    fp = hashlib.sha256(der).hexdigest()
    sans = []
    for typ, val in cert.get("subjectAltName", []) or []:
        if str(typ).lower() == "dns":
            sans.append(str(val))
    cn = None
    subject = cert.get("subject") or []
    for tup in subject:
        for k, v in tup:
            if str(k).lower() == "commonname":
                cn = str(v)
    digest = hashlib.sha256(json.dumps({"sha256": fp, "cn": cn, "sans": sorted(sans)}, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "scan_type": "tls",
        "target": target,
        "status": "ok",
        "fingerprint": fp,
        "details": {
            "digest": digest,
            "cn": cn,
            "sans": sans,
            "issuer": cert.get("issuer"),
            "not_before": cert.get("notBefore"),
            "not_after": cert.get("notAfter"),
        },
    }


def _scan_ssh(target: str, timeout: float = 10.0) -> Dict[str, Any]:
    host = target
    port = 22
    if ":" in target:
        h, p = target.rsplit(":", 1)
        host, port = h, int(p)
    try:
        import paramiko  # type: ignore
    except Exception:
        return {
            "scan_type": "ssh",
            "target": target,
            "status": "error",
            "fingerprint": None,
            "details": {"error": "paramiko_not_installed"},
        }
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            port=port,
            username="",
            password="",
            timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception:
        pass
    transport = client.get_transport()
    if transport is None:
        return {"scan_type": "ssh", "target": target, "status": "error", "fingerprint": None, "details": {"error": "transport_unavailable"}}
    key = transport.get_remote_server_key()
    if key is None:
        return {"scan_type": "ssh", "target": target, "status": "error", "fingerprint": None, "details": {"error": "hostkey_unavailable"}}
    raw = key.asbytes()
    fp_sha256 = base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii")
    return {
        "scan_type": "ssh",
        "target": target,
        "status": "ok",
        "fingerprint": fp_sha256,
        "details": {"algorithm": key.get_name()},
    }


def _insert_scan(scan: Dict[str, Any]) -> None:
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO security_fingerprint_scans
                (id, scan_type, target, status, fingerprint, observed_at, details_json)
                VALUES (:id, :scan_type, :target, :status, :fingerprint, :observed_at, :details_json)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "scan_type": scan.get("scan_type"),
                "target": scan.get("target"),
                "status": scan.get("status", "ok"),
                "fingerprint": scan.get("fingerprint"),
                "observed_at": _utc_now_iso(),
                "details_json": json.dumps(scan.get("details") or {}, ensure_ascii=False),
            },
        )
        db.commit()


def _load_baseline(scan_type: str, target: str) -> Dict[str, Any] | None:
    with db_session() as db:
        row = db.execute(
            text(
                "SELECT baseline_fingerprint, baseline_json FROM security_fingerprint_baselines "
                "WHERE scan_type = :st AND target = :tg LIMIT 1"
            ),
            {"st": scan_type, "tg": target},
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[1]) if row[1] else {}
    except Exception:
        payload = {}
    return {"fingerprint": row[0], "details": payload}


def _upsert_baseline(scan_type: str, target: str, fingerprint: str | None, details: Dict[str, Any]) -> None:
    with db_session() as db:
        upsert(
            db,
            "security_fingerprint_baselines",
            {
                "scan_type": scan_type,
                "target": target,
                "baseline_fingerprint": fingerprint,
                "baseline_json": json.dumps(details or {}, ensure_ascii=False),
                "updated_at": _utc_now_iso(),
            },
            ["scan_type", "target"],
        )
        db.commit()


def _create_alert(
    *,
    alert_type: str,
    severity: str,
    target: str,
    scan_type: str,
    reason: str,
    expected_fingerprint: str | None,
    observed_fingerprint: str | None,
    details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    row = {
        "id": str(uuid.uuid4()),
        "alert_type": alert_type,
        "severity": severity,
        "target": target,
        "scan_type": scan_type,
        "reason": reason,
        "expected_fingerprint": expected_fingerprint,
        "observed_fingerprint": observed_fingerprint,
        "status": "open",
        "note": None,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "details_json": json.dumps(details or {}, ensure_ascii=False),
    }
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO security_fingerprint_alerts
                (id, alert_type, severity, target, scan_type, reason, expected_fingerprint,
                 observed_fingerprint, status, note, created_at, updated_at, details_json)
                VALUES
                (:id, :alert_type, :severity, :target, :scan_type, :reason, :expected_fingerprint,
                 :observed_fingerprint, :status, :note, :created_at, :updated_at, :details_json)
                """
            ),
            row,
        )
        db.commit()
    return row


def _host_matches_cert(host: str, cn: str | None, sans: Iterable[str]) -> bool:
    vals = {str(x).lower() for x in sans if x}
    if cn:
        vals.add(str(cn).lower())
    host = host.lower()
    if host in vals:
        return True
    for entry in vals:
        if entry.startswith("*.") and host.endswith(entry[1:]):
            return True
    return False


def _rules_for_scan(scan: Dict[str, Any], baseline: Dict[str, Any] | None) -> list[Dict[str, Any]]:
    alerts: list[Dict[str, Any]] = []
    scan_type = str(scan.get("scan_type") or "")
    target = str(scan.get("target") or "")
    observed = scan.get("fingerprint")
    details = scan.get("details") or {}
    expected = baseline.get("fingerprint") if baseline else None

    if scan.get("status") != "ok":
        alerts.append(
            _create_alert(
                alert_type="scan_failure",
                severity="medium",
                target=target,
                scan_type=scan_type,
                reason="fingerprint scan failed",
                expected_fingerprint=expected,
                observed_fingerprint=None,
                details={"scan_details": details},
            )
        )
        return alerts

    if baseline and expected and observed and expected != observed:
        alerts.append(
            _create_alert(
                alert_type="fingerprint_drift",
                severity="high",
                target=target,
                scan_type=scan_type,
                reason=f"{scan_type} fingerprint changed from baseline",
                expected_fingerprint=expected,
                observed_fingerprint=observed,
                details={"baseline": baseline.get("details"), "observed": details},
            )
        )

    if scan_type == "headers":
        missing = details.get("missing") or []
        if missing:
            sev = "high" if ("content-security-policy" in missing or "strict-transport-security" in missing) else "medium"
            alerts.append(
                _create_alert(
                    alert_type="missing_security_headers",
                    severity=sev,
                    target=target,
                    scan_type=scan_type,
                    reason="required security headers missing",
                    expected_fingerprint=expected,
                    observed_fingerprint=observed,
                    details={"missing": missing},
                )
            )
        cookie_flags = details.get("cookie_flags") or {}
        if cookie_flags:
            if not cookie_flags.get("secure") or not cookie_flags.get("httponly"):
                alerts.append(
                    _create_alert(
                        alert_type="weak_cookie_flags",
                        severity="medium",
                        target=target,
                        scan_type=scan_type,
                        reason="cookies missing Secure and/or HttpOnly",
                        expected_fingerprint=None,
                        observed_fingerprint=observed,
                        details={"cookie_flags": cookie_flags},
                    )
                )

    if scan_type == "tls":
        host = target.split(":")[0]
        cn = details.get("cn")
        sans = details.get("sans") or []
        if not _host_matches_cert(host, cn, sans):
            alerts.append(
                _create_alert(
                    alert_type="tls_cn_san_mismatch",
                    severity="high",
                    target=target,
                    scan_type=scan_type,
                    reason="TLS certificate CN/SAN does not match target host",
                    expected_fingerprint=expected,
                    observed_fingerprint=observed,
                    details={"host": host, "cn": cn, "sans": sans},
                )
            )

    if scan_type == "ssh":
        alg = str((details or {}).get("algorithm") or "").lower()
        if alg == "ssh-rsa":
            alerts.append(
                _create_alert(
                    alert_type="ssh_algorithm_downgrade",
                    severity="medium",
                    target=target,
                    scan_type=scan_type,
                    reason="SSH endpoint uses legacy ssh-rsa host key",
                    expected_fingerprint=expected,
                    observed_fingerprint=observed,
                    details={"algorithm": alg},
                )
            )
    return alerts


def _rules_reused_fingerprints() -> list[Dict[str, Any]]:
    alerts: list[Dict[str, Any]] = []
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT scan_type, fingerprint, COUNT(DISTINCT target) AS targets
                FROM security_fingerprint_scans
                WHERE observed_at >= datetime('now', '-7 day')
                  AND status = 'ok'
                  AND fingerprint IS NOT NULL
                GROUP BY scan_type, fingerprint
                HAVING COUNT(DISTINCT target) >= 3
                """
            )
        ).fetchall()
    for scan_type, fingerprint, targets in rows or []:
        alerts.append(
            _create_alert(
                alert_type="reused_fingerprint",
                severity="medium",
                target=f"multi:{scan_type}",
                scan_type=str(scan_type),
                reason=f"fingerprint reused across {int(targets)} targets",
                expected_fingerprint=None,
                observed_fingerprint=str(fingerprint),
                details={"targets": int(targets)},
            )
        )
    return alerts


def run_fingerprint_ingestion() -> Dict[str, Any]:
    ensure_fingerprint_tables()
    scans: list[Dict[str, Any]] = []
    alerts: list[Dict[str, Any]] = []

    header_targets = _parse_csv_env("FINGERPRINT_SCAN_TARGETS_HEADERS")
    tls_targets = _parse_csv_env("FINGERPRINT_SCAN_TARGETS_TLS")
    ssh_targets = _parse_csv_env("FINGERPRINT_SCAN_TARGETS_SSH")

    for url in header_targets:
        try:
            scan = _scan_http_headers(url)
        except Exception as e:
            scan = {"scan_type": "headers", "target": url, "status": "error", "fingerprint": None, "details": {"error": str(e)}}
        _insert_scan(scan)
        baseline = _load_baseline("headers", url)
        alerts.extend(_rules_for_scan(scan, baseline))
        if scan.get("status") == "ok":
            if baseline is None or str(os.getenv("FINGERPRINT_AUTO_BASELINE", "1")).lower() in ("1", "true", "yes"):
                _upsert_baseline("headers", url, scan.get("fingerprint"), scan.get("details") or {})
        scans.append(scan)

    for target in tls_targets:
        try:
            scan = _scan_tls(target)
        except Exception as e:
            scan = {"scan_type": "tls", "target": target, "status": "error", "fingerprint": None, "details": {"error": str(e)}}
        _insert_scan(scan)
        baseline = _load_baseline("tls", target)
        alerts.extend(_rules_for_scan(scan, baseline))
        if scan.get("status") == "ok":
            if baseline is None or str(os.getenv("FINGERPRINT_AUTO_BASELINE", "1")).lower() in ("1", "true", "yes"):
                _upsert_baseline("tls", target, scan.get("fingerprint"), scan.get("details") or {})
        scans.append(scan)

    for target in ssh_targets:
        try:
            scan = _scan_ssh(target)
        except Exception as e:
            scan = {"scan_type": "ssh", "target": target, "status": "error", "fingerprint": None, "details": {"error": str(e)}}
        _insert_scan(scan)
        baseline = _load_baseline("ssh", target)
        alerts.extend(_rules_for_scan(scan, baseline))
        if scan.get("status") == "ok":
            if baseline is None or str(os.getenv("FINGERPRINT_AUTO_BASELINE", "1")).lower() in ("1", "true", "yes"):
                _upsert_baseline("ssh", target, scan.get("fingerprint"), scan.get("details") or {})
        scans.append(scan)

    alerts.extend(_rules_reused_fingerprints())
    return {"targets": len(scans), "scans": len(scans), "alerts_created": len(alerts)}


def list_fingerprint_alerts(*, status_filter: str | None = None, severity: str | None = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    ensure_fingerprint_tables()
    q = """
        SELECT id, alert_type, severity, target, scan_type, reason, expected_fingerprint,
               observed_fingerprint, status, note, created_at, updated_at, details_json
        FROM security_fingerprint_alerts
        WHERE 1=1
    """
    params: Dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
    if status_filter:
        q += " AND status = :status_filter"
        params["status_filter"] = status_filter
    if severity:
        q += " AND severity = :severity"
        params["severity"] = severity
    q += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    with db_session() as db:
        rows = db.execute(text(q), params).fetchall()
    items = []
    for r in rows or []:
        try:
            details = json.loads(r[12]) if r[12] else {}
        except Exception:
            details = {}
        items.append(
            {
                "id": r[0],
                "alert_type": r[1],
                "severity": r[2],
                "target": r[3],
                "scan_type": r[4],
                "reason": r[5],
                "expected_fingerprint": r[6],
                "observed_fingerprint": r[7],
                "status": r[8],
                "note": r[9],
                "created_at": r[10],
                "updated_at": r[11],
                "details": details,
            }
        )
    return {"items": items}


def list_fingerprint_scans(*, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    ensure_fingerprint_tables()
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, scan_type, target, status, fingerprint, observed_at, details_json
                FROM security_fingerprint_scans
                ORDER BY observed_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": int(limit), "offset": int(offset)},
        ).fetchall()
    items = []
    for r in rows or []:
        try:
            details = json.loads(r[6]) if r[6] else {}
        except Exception:
            details = {}
        items.append(
            {
                "id": r[0],
                "scan_type": r[1],
                "target": r[2],
                "status": r[3],
                "fingerprint": r[4],
                "observed_at": r[5],
                "details": details,
            }
        )
    return {"items": items}


def update_fingerprint_alert_status(alert_id: str, status: str, note: str | None = None) -> Dict[str, Any]:
    ensure_fingerprint_tables()
    allowed = {"open", "in_progress", "resolved", "ignored"}
    if status not in allowed:
        raise ValueError("invalid status")
    with db_session() as db:
        db.execute(
            text(
                """
                UPDATE security_fingerprint_alerts
                SET status = :status, note = :note, updated_at = :updated_at
                WHERE id = :id
                """
            ),
            {"status": status, "note": note, "updated_at": _utc_now_iso(), "id": alert_id},
        )
        db.commit()
    return {"ok": True, "id": alert_id, "status": status, "note": note}


def _fingerprint_worker(stop_event: threading.Event) -> None:
    interval = int(os.getenv("FINGERPRINT_SCAN_INTERVAL_SECONDS", "1800") or 1800)
    while not stop_event.is_set():
        try:
            run_fingerprint_ingestion()
        except Exception:
            pass
        stop_event.wait(max(60, interval))


def start_fingerprint_worker(app) -> None:
    enabled = str(os.getenv("FINGERPRINT_SCAN_WORKER_ENABLED", "1")).lower() in ("1", "true", "yes")
    if not enabled:
        return
    stop_event = threading.Event()
    thread = threading.Thread(target=_fingerprint_worker, args=(stop_event,), daemon=True)
    thread.start()
    app.state.fingerprint_worker_stop = stop_event
    app.state.fingerprint_worker_thread = thread


def stop_fingerprint_worker(app) -> None:
    try:
        stop_event = getattr(app.state, "fingerprint_worker_stop", None)
        thread = getattr(app.state, "fingerprint_worker_thread", None)
        if stop_event is not None:
            stop_event.set()
        if thread is not None:
            thread.join(timeout=3)
    except Exception:
        pass
