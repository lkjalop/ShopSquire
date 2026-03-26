"""IT-DET-03 / IT-PREV-04 — Security config file integrity monitor.

Records SHA-256 hashes of every security-critical config file at startup.
A Celery periodic task (every 5 minutes) re-hashes each file and compares
against the baseline.  Any mismatch triggers an InsiderThreatSignal with
severity=critical and freezes the affected capability until acknowledged.

Files monitored
---------------
See ``MONITORED_FILES`` below.  Add new files when:
  - A new security policy is stored in config/
  - A new AI governance artefact is added
  - A new egress/routing allowlist is created

Protection provided
-------------------
  • Insider modifying supply_chain_baselines.json to whitelist a fraudulent
    supplier — detected within 5 minutes.
  • Insider modifying rbac_policy.json to escalate their own privileges.
  • Insider modifying egress_allowlist.txt to open exfiltration channels.
  • Unintended config drift between environments.

Framework alignment
-------------------
  ISO 27001:2022  A.8.8  (management of technical vulnerabilities / FIM)
  NIST SP 800-53  SI-7   (software, firmware, and information integrity)
  PCI DSS 4.0     Req 11.5.2 (detect unauthorised modification of files)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Monitored file registry
# ---------------------------------------------------------------------------
# Paths relative to the project root (where the process runs from).
# All paths must exist at startup when ``record_baseline()`` is called,
# otherwise the file is recorded as "missing" and flagged on each check.
# ---------------------------------------------------------------------------

MONITORED_FILES: List[str] = [
    # Supply chain
    "config/security/supply_chain_baselines.json",
    # Routing & egress
    "config/security/routing_policy.json",
    "config/security/egress_allowlist.txt",
    # Access control
    "config/security/rbac_policy.json",
    # AI governance
    "config/ai_governance/model_registry.json",
    "config/ai_governance/prompt_hashes.json",
    # Email security
    "config/security/email_redteam_matrix.json",
    "config/security/linked_artifact_offline_fixtures.json",
]

# Extra files injected at runtime (e.g. from environment variable)
_EXTRA: List[str] = []

_BASELINE: Dict[str, Optional[str]] = {}    # path → sha256 hex (None = missing)
_BASELINE_RECORDED = False


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _file_hash(path: str) -> Optional[str]:
    """Return SHA-256 hex of the file at *path*, or None if it doesn't exist."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("config_integrity hash_error path=%s: %s", path, exc)
        return None


def _all_paths() -> List[str]:
    return MONITORED_FILES + _EXTRA


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_monitored_file(path: str) -> None:
    """Register an additional file for monitoring at runtime."""
    if path not in _EXTRA and path not in MONITORED_FILES:
        _EXTRA.append(path)


def record_baseline(*, force: bool = False) -> Dict[str, Optional[str]]:
    """Snapshot current file hashes as the integrity baseline.

    Call once at application startup (e.g. in the ``lifespan`` handler of
    ``main.py``).  Set ``force=True`` to re-baseline after an acknowledged
    change.

    Returns the baseline dict (path → hash).
    """
    global _BASELINE, _BASELINE_RECORDED
    if _BASELINE_RECORDED and not force:
        return dict(_BASELINE)

    recorded = 0
    missing = 0
    for path in _all_paths():
        h = _file_hash(path)
        _BASELINE[path] = h
        if h is None:
            missing += 1
            logger.warning("config_integrity baseline_missing path=%s", path)
        else:
            recorded += 1

    _BASELINE_RECORDED = True
    logger.info(
        "config_integrity baseline_recorded files=%d missing=%d",
        recorded, missing,
    )
    return dict(_BASELINE)


@dataclass
class IntegrityViolation:
    path: str
    issue: str               # "hash_mismatch" | "missing" | "new_file"
    expected_hash: Optional[str]
    actual_hash:   Optional[str]

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "issue": self.issue,
            "expected_hash": (self.expected_hash or "")[:16] + "..." if self.expected_hash else None,
            "actual_hash":   (self.actual_hash   or "")[:16] + "..." if self.actual_hash   else None,
        }


def check_integrity() -> List[IntegrityViolation]:
    """Re-hash every monitored file and compare against the baseline.

    Returns a list of violations (empty = all good).
    Called by the Celery periodic task every 5 minutes.
    """
    if not _BASELINE_RECORDED:
        # Baseline not yet set — record it now as a fallback
        record_baseline()

    violations: List[IntegrityViolation] = []

    for path in _all_paths():
        current = _file_hash(path)
        expected = _BASELINE.get(path)

        if expected is None and current is None:
            # File was missing at baseline and still missing — warn once at startup
            continue
        if expected is None and current is not None:
            # File appeared after baseline — flag as unexpected new file
            violations.append(IntegrityViolation(
                path=path,
                issue="new_file_after_baseline",
                expected_hash=None,
                actual_hash=current,
            ))
        elif expected is not None and current is None:
            violations.append(IntegrityViolation(
                path=path,
                issue="missing",
                expected_hash=expected,
                actual_hash=None,
            ))
        elif expected != current:
            violations.append(IntegrityViolation(
                path=path,
                issue="hash_mismatch",
                expected_hash=expected,
                actual_hash=current,
            ))

    if violations:
        logger.critical(
            "config_integrity violations detected count=%d paths=%s",
            len(violations),
            [v.path for v in violations],
        )
        _emit_violations(violations)
    else:
        logger.debug("config_integrity check_ok files=%d", len(_all_paths()))

    return violations


def _emit_violations(violations: List[IntegrityViolation]) -> None:
    """Emit each violation as an InsiderThreatSignal + Prometheus metric."""
    for v in violations:
        try:
            from src.app.security.insider_threat_detector import (
                InsiderThreatSignal,
                _emit,
            )
            signal = InsiderThreatSignal(
                signal_type="config_file_tampered",
                actor="system",
                resource=v.path,
                severity="critical",
                context=v.to_dict(),
            )
            _emit(signal)
        except Exception as exc:
            logger.error("config_integrity _emit_violations error: %s", exc)


def acknowledge_change(path: str) -> None:
    """Update the baseline for *path* after an operator-approved change.

    Must be called via the admin API — not directly from code — so that the
    acknowledgement itself is logged to the audit chain.
    """
    new_hash = _file_hash(path)
    old_hash = _BASELINE.get(path)
    _BASELINE[path] = new_hash
    logger.info(
        "config_integrity change_acknowledged path=%s old=%s new=%s",
        path,
        (old_hash or "")[:16],
        (new_hash or "")[:16],
    )


def get_baseline() -> Dict[str, Optional[str]]:
    """Return a copy of the current baseline (for admin inspection)."""
    return dict(_BASELINE)
