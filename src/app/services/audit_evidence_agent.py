from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Tuple

import os
from sqlalchemy import text

from src.app.models.db import db_session


Status = str

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class RuleResult:
    rule_id: int
    category: str
    check: str
    status: Status
    tags: List[str]
    evidence_refs: List[Dict[str, Any]]
    notes: str | None = None


def _table_exists(db, table: str) -> bool:
    try:
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = :name",
            {"name": table},
        ).fetchone()
        if row:
            return True
    except Exception:
        pass
    try:
        row = db.execute(text("SELECT to_regclass(:name)"), {"name": table}).fetchone()
        return bool(row and row[0])
    except Exception:
        return False


def _columns_for(db, table: str) -> List[str]:
    try:
        t = str(table or "").strip()
        if not _IDENT_RE.match(t):
            return []
        rows = db.execute(text(f"PRAGMA table_info({t})")).fetchall()
        if rows:
            return [r[1] for r in rows]
    except Exception:
        pass
    try:
        rows = db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :table",
            {"table": table},
        ).fetchall()
        return [r[0] for r in rows] if rows else []
    except Exception:
        return []


def _fact_or_warn(facts: Dict[str, Any], key: str, expect: bool = True) -> Tuple[Status, List[Dict[str, Any]], str | None]:
    if key in facts:
        value = bool(facts.get(key))
        status = "PASS" if value == expect else "FAIL"
        return status, [{"type": "fact", "id": key, "value": value}], None
    return "WARN", [{"type": "fact", "id": key, "value": None}], "Evidence not supplied"


class AuditEvidenceAgent:
    """Deterministic checks for audit readiness (rules 1–50)."""

    RULES: List[Dict[str, Any]] = [
        {"id": 1, "category": "log_integrity", "check": "append_only_enforcement", "tags": ["SOX", "SOC2", "ISO27001"]},
        {"id": 2, "category": "log_integrity", "check": "hash_chain_continuity", "tags": ["SOX", "SOC2", "EUAI"]},
        {"id": 3, "category": "log_integrity", "check": "timestamp_trust", "tags": ["SOX", "SOC2", "ISO27001"]},
        {"id": 4, "category": "log_integrity", "check": "required_event_fields", "tags": ["SOX", "SOC2", "EUAI"]},
        {"id": 5, "category": "log_integrity", "check": "trace_coverage_financial", "tags": ["SOX", "SOC2"]},
        {"id": 6, "category": "log_integrity", "check": "policy_model_version_recorded", "tags": ["EUAI", "ISO42001", "SOC2"]},
        {"id": 7, "category": "log_integrity", "check": "evidence_reference_integrity", "tags": ["SOX", "SOC2", "ISO27001"]},
        {"id": 8, "category": "privacy", "check": "redaction_enforced", "tags": ["GDPR", "CPRA", "AU"]},
        {"id": 9, "category": "privacy", "check": "retention_policy_applied", "tags": ["SOC2", "ISO27001", "GDPR", "AU"]},
        {"id": 10, "category": "access_control", "check": "log_access_control", "tags": ["SOX", "SOC2", "ISO27001"]},
        {"id": 11, "category": "access_control", "check": "mfa_enforced", "tags": ["SOX", "SOC2", "ISO27001"]},
        {"id": 12, "category": "access_control", "check": "least_privilege_prod_db", "tags": ["SOX", "SOC2"]},
        {"id": 13, "category": "access_control", "check": "segregation_request_approve", "tags": ["SOX", "SOC2"]},
        {"id": 14, "category": "access_control", "check": "jit_access", "tags": ["SOX", "SOC2", "ISO27001"]},
        {"id": 15, "category": "access_control", "check": "quarterly_access_reviews", "tags": ["SOX", "SOC2"]},
        {"id": 16, "category": "access_control", "check": "service_identity_signing", "tags": ["SOC2", "ISO27001"]},
        {"id": 17, "category": "access_control", "check": "break_glass_controls", "tags": ["SOX", "SOC2"]},
        {"id": 18, "category": "access_control", "check": "human_escalation_identity", "tags": ["SOX", "SOC2", "EUAI"]},
        {"id": 19, "category": "change_mgmt", "check": "prod_changes_via_pr", "tags": ["SOX", "SOC2"]},
        {"id": 20, "category": "change_mgmt", "check": "immutable_build_artifacts", "tags": ["SOC2", "ISO27001"]},
        {"id": 21, "category": "change_mgmt", "check": "feature_flags_versioned", "tags": ["SOX", "SOC2"]},
        {"id": 22, "category": "change_mgmt", "check": "emergency_change_workflow", "tags": ["SOX", "SOC2"]},
        {"id": 23, "category": "change_mgmt", "check": "prompt_template_versioned", "tags": ["ISO42001", "EUAI"]},
        {"id": 24, "category": "change_mgmt", "check": "policy_rules_change_control", "tags": ["SOX", "SOC2"]},
        {"id": 25, "category": "change_mgmt", "check": "dependency_supplier_risk", "tags": ["SOC2", "ISO27001"]},
        {"id": 26, "category": "change_mgmt", "check": "evidence_reproducibility", "tags": ["SOX", "SOC2"]},
        {"id": 27, "category": "financial_controls", "check": "refund_authorization_gate", "tags": ["SOX", "SOC2"]},
        {"id": 28, "category": "financial_controls", "check": "dual_approval_high_refund", "tags": ["SOX", "SOC2"]},
        {"id": 29, "category": "financial_controls", "check": "idempotent_refunds", "tags": ["SOX", "SOC2"]},
        {"id": 30, "category": "financial_controls", "check": "ledger_reconciliation", "tags": ["SOX"]},
        {"id": 31, "category": "financial_controls", "check": "exception_handling_path", "tags": ["SOX", "SOC2"]},
        {"id": 32, "category": "financial_controls", "check": "payment_integration_logging", "tags": ["SOX", "SOC2"]},
        {"id": 33, "category": "financial_controls", "check": "chargeback_traceability", "tags": ["SOX", "SOC2"]},
        {"id": 34, "category": "financial_controls", "check": "financial_data_access_monitoring", "tags": ["SOX", "SOC2"]},
        {"id": 35, "category": "privacy", "check": "data_inventory_exists", "tags": ["GDPR", "CPRA", "AU"]},
        {"id": 36, "category": "privacy", "check": "processing_registry", "tags": ["GDPR", "CPRA", "AU"]},
        {"id": 37, "category": "privacy", "check": "dsar_intake_verification", "tags": ["GDPR", "CPRA"]},
        {"id": 38, "category": "privacy", "check": "dsar_completion_audit", "tags": ["GDPR", "CPRA"]},
        {"id": 39, "category": "privacy", "check": "retention_disposal_enforced", "tags": ["GDPR", "AU"]},
        {"id": 40, "category": "privacy", "check": "breach_notification_workflow", "tags": ["AU"]},
        {"id": 41, "category": "privacy", "check": "logging_minimization", "tags": ["GDPR", "CPRA", "AU"]},
        {"id": 42, "category": "privacy", "check": "third_party_processing_controls", "tags": ["GDPR", "SOC2"]},
        {"id": 43, "category": "ai_governance", "check": "ai_decision_classification", "tags": ["EUAI", "ISO42001"]},
        {"id": 44, "category": "ai_governance", "check": "ai_record_keeping", "tags": ["EUAI"]},
        {"id": 45, "category": "ai_governance", "check": "model_registry_provenance", "tags": ["ISO42001"]},
        {"id": 46, "category": "ai_governance", "check": "human_oversight_triggers", "tags": ["ISO42001", "EUAI"]},
        {"id": 47, "category": "ai_governance", "check": "prompt_injection_logging", "tags": ["SOC2", "ISO27001", "EUAI"]},
        {"id": 48, "category": "ai_governance", "check": "output_handling_sanitization", "tags": ["SOC2", "ISO27001"]},
        {"id": 49, "category": "ai_governance", "check": "budget_rate_limiting", "tags": ["SOC2", "EUAI"]},
        {"id": 50, "category": "ai_governance", "check": "audit_report_governance", "tags": ["ISO19011"]},
    ]

    def run(self, scope: Dict[str, Any] | None = None) -> Dict[str, Any]:
        scope = scope or {}
        facts: Dict[str, Any] = scope.get("facts") or {}
        results: List[RuleResult] = []
        summary = {"pass": 0, "warn": 0, "fail": 0}

        for rule in self.RULES:
            status, evidence, notes = self._evaluate_rule(rule, facts)
            if status == "PASS":
                summary["pass"] += 1
            elif status == "FAIL":
                summary["fail"] += 1
            else:
                summary["warn"] += 1
            results.append(
                RuleResult(
                    rule_id=rule["id"],
                    category=rule["category"],
                    check=rule["check"],
                    status=status,
                    tags=rule["tags"],
                    evidence_refs=evidence,
                    notes=notes,
                )
            )

        return {
            "scope": scope.get("scope") or "default",
            "generated_at": scope.get("generated_at"),
            "summary": summary,
            "rules": [r.__dict__ for r in results],
        }

    def _evaluate_rule(self, rule: Dict[str, Any], facts: Dict[str, Any]) -> Tuple[Status, List[Dict[str, Any]], str | None]:
        check = rule["check"]
        if check == "required_event_fields":
            return self._check_required_event_fields()
        if check == "policy_model_version_recorded":
            return self._check_policy_version()
        if check == "ai_record_keeping":
            return self._check_ai_recordkeeping()
        if check == "prompt_injection_logging":
            return self._check_security_logging()
        if check == "retention_policy_applied":
            return self._check_retention()
        if check in {
            "mfa_enforced",
            "least_privilege_prod_db",
            "segregation_request_approve",
            "jit_access",
            "quarterly_access_reviews",
            "service_identity_signing",
            "break_glass_controls",
            "human_escalation_identity",
            "prod_changes_via_pr",
            "immutable_build_artifacts",
            "feature_flags_versioned",
            "emergency_change_workflow",
            "prompt_template_versioned",
            "policy_rules_change_control",
            "dependency_supplier_risk",
            "evidence_reproducibility",
            "refund_authorization_gate",
            "dual_approval_high_refund",
            "idempotent_refunds",
            "ledger_reconciliation",
            "exception_handling_path",
            "payment_integration_logging",
            "chargeback_traceability",
            "financial_data_access_monitoring",
            "data_inventory_exists",
            "processing_registry",
            "dsar_intake_verification",
            "dsar_completion_audit",
            "retention_disposal_enforced",
            "breach_notification_workflow",
            "logging_minimization",
            "third_party_processing_controls",
            "ai_decision_classification",
            "model_registry_provenance",
            "human_oversight_triggers",
            "output_handling_sanitization",
            "budget_rate_limiting",
            "audit_report_governance",
            "append_only_enforcement",
            "hash_chain_continuity",
            "timestamp_trust",
            "trace_coverage_financial",
            "evidence_reference_integrity",
            "redaction_enforced",
            "log_access_control",
        }:
            return _fact_or_warn(facts, check)
        return "WARN", [{"type": "rule", "id": check}], "No evaluator available"

    def _check_required_event_fields(self) -> Tuple[Status, List[Dict[str, Any]], str | None]:
        try:
            with db_session() as db:
                if not _table_exists(db, "decision_trace_events"):
                    return "WARN", [{"type": "db_table", "id": "decision_trace_events", "exists": False}], "Trace table missing"
                cols = _columns_for(db, "decision_trace_events")
                required = {"trace_id", "event_type", "source_type", "payload", "created_at"}
                missing = [c for c in required if c not in cols]
                if missing:
                    return "FAIL", [{"type": "db_table", "id": "decision_trace_events", "missing": missing}], "Missing required columns"
                return "PASS", [{"type": "db_table", "id": "decision_trace_events", "columns": list(required)}], None
        except Exception as exc:
            return "WARN", [{"type": "db_table", "id": "decision_trace_events", "error": str(exc)}], "Unable to inspect DB"

    def _check_policy_version(self) -> Tuple[Status, List[Dict[str, Any]], str | None]:
        try:
            with db_session() as db:
                if not _table_exists(db, "decision_logs"):
                    return "WARN", [{"type": "db_table", "id": "decision_logs", "exists": False}], "Decision log missing"
                cols = _columns_for(db, "decision_logs")
                if "policy_version" in cols:
                    return "PASS", [{"type": "db_table", "id": "decision_logs", "column": "policy_version"}], None
                return "FAIL", [{"type": "db_table", "id": "decision_logs", "missing": ["policy_version"]}], "policy_version column missing"
        except Exception as exc:
            return "WARN", [{"type": "db_table", "id": "decision_logs", "error": str(exc)}], "Unable to inspect DB"

    def _check_ai_recordkeeping(self) -> Tuple[Status, List[Dict[str, Any]], str | None]:
        try:
            with db_session() as db:
                if _table_exists(db, "decision_trace_events"):
                    return "PASS", [{"type": "db_table", "id": "decision_trace_events"}], None
        except Exception as exc:
            return "WARN", [{"type": "db_table", "id": "decision_trace_events", "error": str(exc)}], "Unable to inspect DB"
        return "WARN", [{"type": "db_table", "id": "decision_trace_events", "exists": False}], "Trace table missing"

    def _check_security_logging(self) -> Tuple[Status, List[Dict[str, Any]], str | None]:
        try:
            with db_session() as db:
                if _table_exists(db, "security_observer_timeseries"):
                    return "PASS", [{"type": "db_table", "id": "security_observer_timeseries"}], None
        except Exception as exc:
            return "WARN", [{"type": "db_table", "id": "security_observer_timeseries", "error": str(exc)}], "Unable to inspect DB"
        return "WARN", [{"type": "db_table", "id": "security_observer_timeseries", "exists": False}], "Security timeseries missing"

    def _check_retention(self) -> Tuple[Status, List[Dict[str, Any]], str | None]:
        ttl_chat = os.getenv("RETENTION_CHAT_TTL_HOURS")
        ttl_cv = os.getenv("RETENTION_CV_EVIDENCE_DAYS") or os.getenv("RETENTION_CV_DAYS")
        ttl_audit = os.getenv("RETENTION_AUDIT_DAYS")
        if ttl_chat and ttl_cv and ttl_audit:
            return "PASS", [{"type": "env", "id": "RETENTION_*", "values": {"chat": ttl_chat, "cv": ttl_cv, "audit": ttl_audit}}], None
        return "WARN", [{"type": "env", "id": "RETENTION_*", "values": {"chat": ttl_chat, "cv": ttl_cv, "audit": ttl_audit}}], "Retention env vars missing"
