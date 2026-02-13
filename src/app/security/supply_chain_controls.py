from __future__ import annotations

from typing import Any, Dict, List
import base64
import hashlib
import hmac
import json
import os

from src.app.models.db import db_session
from sqlalchemy import text


def _load_kev() -> Dict[str, Any]:
    path = os.getenv("KEV_CATALOG_PATH", "config/security/taxonomy/kev_catalog.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _collect_cves(sbom: Dict[str, Any]) -> List[str]:
    cves: set[str] = set()
    vulns = sbom.get("vulnerabilities")
    if isinstance(vulns, list):
        for v in vulns:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id") or "").upper()
            if vid.startswith("CVE-"):
                cves.add(vid)
    comps = sbom.get("components")
    if isinstance(comps, list):
        for c in comps:
            if not isinstance(c, dict):
                continue
            vv = c.get("vulnerabilities")
            if isinstance(vv, list):
                for item in vv:
                    vid = str((item or {}).get("id") or "").upper()
                    if vid.startswith("CVE-"):
                        cves.add(vid)
    return sorted(cves)


def ingest_sbom_and_correlate(sbom: Dict[str, Any], *, tenant_id: str | None = None) -> Dict[str, Any]:
    kev = _load_kev()
    cves = _collect_cves(sbom or {})
    kev_hits = [c for c in cves if c in kev]
    risk_band = "low"
    if kev_hits:
        risk_band = "high"
    elif cves:
        risk_band = "medium"
    return {
        "tenant_id": tenant_id,
        "component_count": len(sbom.get("components") or []) if isinstance(sbom.get("components"), list) else 0,
        "cve_count": len(cves),
        "cves": cves[:128],
        "kev_hits": kev_hits[:128],
        "risk_band": risk_band,
        "requires_security_review": bool(kev_hits),
    }


def check_oauth_scope_anomaly(
    *,
    partner: str,
    granted_scopes: List[str],
    tenant_id: str | None = None,
    baseline_scopes: List[str] | None = None,
) -> Dict[str, Any]:
    partner_n = str(partner or "").strip().lower() or "unknown"
    tenant = str(tenant_id or "default")
    granted = sorted({str(s).strip() for s in (granted_scopes or []) if str(s).strip()})
    _ensure_scope_table()
    baseline = sorted({str(s).strip() for s in (baseline_scopes or []) if str(s).strip()})
    try:
        if not baseline:
            with db_session() as db:
                row = db.execute(
                    text(
                        """
                        SELECT scopes_json
                        FROM partner_scope_baselines
                        WHERE tenant_id=:tenant AND partner=:partner
                        """
                    ),
                    {"tenant": tenant, "partner": partner_n},
                ).fetchone()
            if row and row[0]:
                baseline = sorted({str(s).strip() for s in json.loads(row[0] or "[]") if str(s).strip()})
    except Exception:
        baseline = baseline or []
    if not baseline:
        baseline = list(granted)
    unexpected = sorted(set(granted) - set(baseline))
    missing = sorted(set(baseline) - set(granted))
    high_risk_scopes = [s for s in unexpected if any(x in s for x in ("admin", "write", "billing", "payments", "secrets"))]
    anomaly_score = min(1.0, (0.2 * len(unexpected)) + (0.35 if high_risk_scopes else 0.0))
    out = {
        "tenant_id": tenant_id,
        "partner": partner_n,
        "baseline_scopes": baseline,
        "granted_scopes": granted,
        "unexpected_scopes": unexpected,
        "missing_scopes": missing,
        "high_risk_scopes": high_risk_scopes,
        "anomaly_score": round(float(anomaly_score), 3),
        "requires_security_review": bool(high_risk_scopes),
    }
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO partner_scope_baselines (tenant_id, partner, scopes_json, updated_at)
                    VALUES (:tenant, :partner, :scopes, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id, partner) DO UPDATE SET
                      scopes_json=:scopes,
                      updated_at=CURRENT_TIMESTAMP
                    """
                ),
                {"tenant": tenant, "partner": partner_n, "scopes": json.dumps(baseline, ensure_ascii=False)},
            )
            db.commit()
    except Exception:
        pass
    return out


def verify_partner_artifact_signature(
    *,
    artifact_b64: str,
    signature: str,
    signer: str | None = None,
    algorithm: str = "sha256",
) -> Dict[str, Any]:
    try:
        blob = base64.b64decode(artifact_b64.encode("utf-8"), validate=False)
    except Exception:
        blob = b""
    artifact_sha256 = hashlib.sha256(blob).hexdigest() if blob else None
    signer_name = str(signer or "").strip().lower()
    trusted = {x.strip().lower() for x in str(os.getenv("TRUSTED_PARTNER_SIGNERS", "") or "").split(",") if x.strip()}
    signer_trusted = bool(signer_name and signer_name in trusted) if trusted else bool(signer_name)
    verified = False
    mode = str(os.getenv("ARTIFACT_SIGNATURE_MODE", "digest") or "digest").strip().lower()
    sig = str(signature or "").strip().lower()
    if blob and sig:
        if mode == "hmac":
            secret = str(os.getenv("PARTNER_ARTIFACT_HMAC_SECRET", "") or "")
            if secret:
                expect = hmac.new(secret.encode("utf-8"), blob, hashlib.sha256).hexdigest().lower()
                verified = hmac.compare_digest(expect, sig)
        else:
            if algorithm.lower() == "sha256":
                expect = hashlib.sha256(blob).hexdigest().lower()
                verified = hmac.compare_digest(expect, sig)
    return {
        "algorithm": algorithm,
        "mode": mode,
        "artifact_sha256": artifact_sha256,
        "signature_verified": bool(verified),
        "signer": signer_name or None,
        "signer_trusted": signer_trusted,
        "requires_security_review": not (verified and signer_trusted),
    }


def verify_slsa_attestation(attestation: Dict[str, Any], *, sbom: Dict[str, Any] | None = None) -> Dict[str, Any]:
    a = attestation if isinstance(attestation, dict) else {}
    predicate_type = str(a.get("predicateType") or a.get("predicate_type") or "")
    predicate = a.get("predicate") if isinstance(a.get("predicate"), dict) else {}
    builder = predicate.get("builder") if isinstance(predicate.get("builder"), dict) else {}
    build_type = str(predicate.get("buildType") or "")
    materials = predicate.get("materials") if isinstance(predicate.get("materials"), list) else []

    checks: list[Dict[str, Any]] = []
    checks.append({"check": "predicate_type_present", "ok": bool(predicate_type)})
    checks.append({"check": "builder_id_present", "ok": bool(str(builder.get("id") or "").strip())})
    checks.append({"check": "build_type_present", "ok": bool(build_type)})
    checks.append({"check": "materials_present", "ok": bool(materials)})

    unknown_materials = 0
    for m in materials:
        if not isinstance(m, dict):
            unknown_materials += 1
            continue
        dig = m.get("digest")
        if not isinstance(dig, dict) or not dig:
            unknown_materials += 1
    checks.append({"check": "materials_digest_complete", "ok": unknown_materials == 0, "unknown_materials": unknown_materials})

    slsa_level = 1
    if bool(str(builder.get("id") or "").strip()) and bool(materials) and unknown_materials == 0:
        slsa_level = 2
    if slsa_level == 2 and "https://slsa.dev/provenance" in predicate_type and str(build_type).strip():
        slsa_level = 3

    sbom_cves = _collect_cves(sbom or {}) if isinstance(sbom, dict) else []
    kev = _load_kev()
    kev_hits = [c for c in sbom_cves if c in kev]
    risk_band = "low"
    if kev_hits:
        risk_band = "high"
    elif unknown_materials > 0 or slsa_level < 2:
        risk_band = "medium"

    return {
        "slsa_level_estimate": slsa_level,
        "predicate_type": predicate_type or None,
        "builder_id": builder.get("id"),
        "materials_count": len(materials),
        "checks": checks,
        "sbom_cve_count": len(sbom_cves),
        "kev_hits": kev_hits[:128],
        "risk_band": risk_band,
        "requires_security_review": bool(kev_hits) or slsa_level < 2 or unknown_materials > 0,
    }


def _ensure_scope_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS partner_scope_baselines (
                      tenant_id TEXT NOT NULL,
                      partner TEXT NOT NULL,
                      scopes_json TEXT NOT NULL,
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (tenant_id, partner)
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass
