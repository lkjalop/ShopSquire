from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session


_DEFAULT_CONTROL_FILES = [
    "config/feature_flags.json",
    "config/confidence_calibration.json",
    "config/security/cv_playbooks.json",
    "src/app/security/email_security_rules.py",
    "src/app/security/yara_email_scan.py",
    "src/app/security/semantic_bec_scorer.py",
    "src/app/security/ransomware_detector.py",
    "src/app/security/bimi_verifier.py",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _workspace_root() -> Path:
    # c:\AI\ShopSquire\src\app\security\policy_pack_release.py -> root is parents[3]
    return Path(__file__).resolve().parents[3]


def collect_policy_manifest() -> Dict[str, Any]:
    root = _workspace_root()
    items: List[Dict[str, Any]] = []
    digest_source = []
    for rel in _DEFAULT_CONTROL_FILES:
        p = (root / rel).resolve()
        file_hash = _sha256_file(p)
        exists = file_hash is not None
        row = {
            "path": rel,
            "exists": exists,
            "sha256": file_hash,
            "size_bytes": (p.stat().st_size if exists else None),
        }
        items.append(row)
        digest_source.append(f"{rel}:{file_hash or 'missing'}")
    manifest_hash = hashlib.sha256("\n".join(digest_source).encode("utf-8")).hexdigest()
    version = f"email-security-pack-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{manifest_hash[:10]}"
    return {
        "version": version,
        "generated_at": _now_iso(),
        "manifest_hash": manifest_hash,
        "control_files": items,
    }


def _sign_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    key = str(os.getenv("EMAIL_SECURITY_POLICY_SIGNING_KEY", "dev-insecure-key-change-me") or "dev-insecure-key-change-me")
    key_id = str(os.getenv("EMAIL_SECURITY_POLICY_SIGNING_KEY_ID", "local-dev-key") or "local-dev-key")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {"algorithm": "hmac-sha256", "key_id": key_id, "signature": sig}


def verify_release_signature(release: Dict[str, Any]) -> Dict[str, Any]:
    manifest = release.get("manifest") if isinstance(release.get("manifest"), dict) else {}
    notes = release.get("release_notes") if isinstance(release.get("release_notes"), dict) else {}
    payload = {"manifest": manifest, "release_notes": notes}
    expected = _sign_payload(payload)
    got = str((release.get("signature") or {}).get("signature") or "")
    ok = bool(got) and hmac.compare_digest(got, str(expected.get("signature") or ""))
    return {
        "ok": ok,
        "algorithm": "hmac-sha256",
        "key_id": str((release.get("signature") or {}).get("key_id") or expected.get("key_id")),
    }


def _ensure_table() -> None:
    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS email_security_policy_pack_releases (
                  id TEXT PRIMARY KEY,
                  version TEXT NOT NULL,
                  manifest_hash TEXT NOT NULL,
                  manifest_json TEXT NOT NULL,
                  release_notes_json TEXT NOT NULL,
                  signature_json TEXT NOT NULL,
                  signer TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_email_security_policy_pack_releases_version
                ON email_security_policy_pack_releases (version)
                """
            )
        )
        db.commit()


def create_policy_pack_release(*, changelog: List[str] | None = None, signer: str | None = None) -> Dict[str, Any]:
    _ensure_table()
    manifest = collect_policy_manifest()
    notes = {
        "title": "Email security policy pack release",
        "version": manifest.get("version"),
        "created_at": _now_iso(),
        "changelog": [str(x) for x in (changelog or []) if str(x or "").strip()] or ["No changelog provided."],
    }
    payload = {"manifest": manifest, "release_notes": notes}
    sig = _sign_payload(payload)
    rel_id = f"ppr-{hashlib.sha256((str(manifest.get('version')) + notes['created_at']).encode('utf-8')).hexdigest()[:16]}"
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO email_security_policy_pack_releases
                (id, version, manifest_hash, manifest_json, release_notes_json, signature_json, signer, created_at)
                VALUES
                (:id, :version, :manifest_hash, :manifest_json, :release_notes_json, :signature_json, :signer, CURRENT_TIMESTAMP)
                """
            ),
            {
                "id": rel_id,
                "version": str(manifest.get("version") or ""),
                "manifest_hash": str(manifest.get("manifest_hash") or ""),
                "manifest_json": json.dumps(manifest, ensure_ascii=False),
                "release_notes_json": json.dumps(notes, ensure_ascii=False),
                "signature_json": json.dumps(sig, ensure_ascii=False),
                "signer": str(signer or "system"),
            },
        )
        db.commit()
    out = {"id": rel_id, "manifest": manifest, "release_notes": notes, "signature": sig, "signer": str(signer or "system")}
    out["verification"] = verify_release_signature(out)
    return out


def list_policy_pack_releases(*, limit: int = 20) -> Dict[str, Any]:
    _ensure_table()
    lim = max(1, min(int(limit or 20), 200))
    items: List[Dict[str, Any]] = []
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, version, manifest_hash, manifest_json, release_notes_json, signature_json, signer, created_at
                FROM email_security_policy_pack_releases
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": lim},
        ).fetchall()
    for r in rows or []:
        rel = {
            "id": str(r[0]),
            "version": str(r[1]),
            "manifest_hash": str(r[2]),
            "manifest": json.loads(r[3] or "{}"),
            "release_notes": json.loads(r[4] or "{}"),
            "signature": json.loads(r[5] or "{}"),
            "signer": str(r[6] or "system"),
            "created_at": str(r[7] or ""),
        }
        rel["verification"] = verify_release_signature(rel)
        items.append(rel)
    return {"items": items, "count": len(items), "limit": lim}


def get_policy_pack_release(version: str) -> Dict[str, Any]:
    _ensure_table()
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT id, version, manifest_hash, manifest_json, release_notes_json, signature_json, signer, created_at
                FROM email_security_policy_pack_releases
                WHERE version = :version
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"version": str(version or "")},
        ).fetchone()
    if row is None:
        return {"found": False}
    rel = {
        "found": True,
        "id": str(row[0]),
        "version": str(row[1]),
        "manifest_hash": str(row[2]),
        "manifest": json.loads(row[3] or "{}"),
        "release_notes": json.loads(row[4] or "{}"),
        "signature": json.loads(row[5] or "{}"),
        "signer": str(row[6] or "system"),
        "created_at": str(row[7] or ""),
    }
    rel["verification"] = verify_release_signature(rel)
    return rel
