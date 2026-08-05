"""Pure, subprocess-safe return artifact inspection functions."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


def inspect_security(*, content_b64: str, filename: str, content_type: str) -> dict[str, Any]:
    from src.app.services.intake_gate import strict_binary_ingest_gate

    raw = base64.b64decode(content_b64, validate=True)
    verdict = strict_binary_ingest_gate(
        filename=filename,
        content_type=content_type,
        blob=raw,
        size_bytes=len(raw),
    )
    reasons = [str(value)[:120] for value in (verdict.get("reasons") or [])[:20]]
    coverage = [str(verdict.get("gate") or "strict_binary_ingest")]
    blocked = bool(verdict.get("blocked") or verdict.get("status") == "blocked")
    degraded = str(verdict.get("status") or "degraded") == "degraded"

    lowered_name = Path(str(filename or "upload.bin")).name.lower()
    lowered_type = str(content_type or "").lower()
    is_archive = raw[:4] == b"PK\x03\x04" or lowered_name.endswith(
        (".zip", ".tar", ".tgz", ".gz", ".bz2")
    )
    is_office = lowered_name.endswith(
        (".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm")
    ) or "officedocument" in lowered_type or "macroenabled" in lowered_type

    # Reuse the same deterministic document parser used by supplier-email
    # evidence. It records structural indicators only and never follows an
    # external relationship or executes active content.
    is_csv = lowered_name.endswith(".csv") or lowered_type in {"text/csv", "application/csv"}
    if "pdf" in lowered_type or lowered_name.endswith(".pdf") or is_office or is_csv:
        try:
            from src.app.security.email_attachment_intel import _forensics_from_attachments
            from src.app.security.email_attachment_parser import hydrate_attachments_from_bytes

            hydrated = hydrate_attachments_from_bytes({"attachments": [{
                "name": lowered_name,
                "content_type": content_type,
                "content_b64": content_b64,
            }]})["attachments"][0]
            indicators, _ = _forensics_from_attachments([hydrated])
            reasons.extend(str(item.get("type") or "document_active_content") for item in indicators)
            formula_hits = int(hydrated.get("spreadsheet_formula_neutralized") or 0)
            if formula_hits:
                reasons.append("spreadsheet_formula_neutralized")
            from src.app.services.intake_gate import sanitize_ocr_text

            _, text_safety = sanitize_ocr_text(str(hydrated.get("extracted_text") or ""))
            instruction_hits = int(text_safety.get("removed_instruction_hits") or 0)
            if instruction_hits:
                reasons.append("untrusted_document_instruction")
            parse_errors = [str(value) for value in (hydrated.get("parse_errors") or [])]
            if parse_errors:
                degraded = True
                reasons.extend(f"document_parser:{value}" for value in parse_errors)
            if indicators or formula_hits or instruction_hits:
                blocked = True
            coverage.append("document_active_content_forensics")
        except Exception as exc:
            degraded = True
            reasons.append(f"document_forensics_failed:{type(exc).__name__}")

    if is_archive and not is_office:
        try:
            from src.app.security.archive_sandbox import inspect_archive

            archive = inspect_archive(raw, filename=lowered_name)
            if not archive.allowed:
                blocked = True
                reasons.extend(f"archive:{reason}" for reason in archive.reasons)
            if archive.error:
                degraded = True
                reasons.append(f"archive:{archive.error}")
            coverage.append("archive_sandbox")
        except Exception as exc:
            degraded = True
            reasons.append(f"archive_inspection_failed:{type(exc).__name__}")

    status = "blocked" if blocked else "degraded" if degraded else "clean"
    return {
        "status": status,
        "blocked": blocked,
        "reasons": sorted(set(reasons))[:20],
        "content_type_sniffed": verdict.get("content_type_sniffed"),
        "coverage": coverage,
    }


def inspect_visual(*, content_b64: str, filename: str, content_type: str) -> dict[str, Any]:
    raw = base64.b64decode(content_b64, validate=True)
    if not str(content_type or "").lower().startswith("image/"):
        return {
            "status": "not_applicable", "provider": None, "text_excerpt": "",
            "confidence": None, "degradation_reason": None,
        }
    from src.app.services.cv_ocr import extract_text

    result = extract_text(raw)
    text = str(result.get("text") or "")
    return {
        "status": "degraded" if result.get("degraded") else "completed",
        "provider": result.get("provider"),
        # The complete raw OCR string is not copied into the operational model.
        "text_excerpt": text[:500],
        "confidence": result.get("confidence"),
        "degradation_reason": result.get("degradation_reason"),
        "filename": str(filename)[:160],
    }
