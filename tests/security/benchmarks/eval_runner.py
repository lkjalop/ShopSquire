from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.app.security.email_security import evaluate_email_security
from tests.security.synthetic_samples import (
    SYNTHETIC_AUTHORITY,
    bytes_for_legacy_fixture,
)


_ROOT = Path(__file__).resolve().parents[3]
_GROUND_TRUTH = Path(__file__).resolve().parent / "ground_truth"


def _load_case(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid benchmark case: {path}")
    return payload


def iter_cases() -> Iterable[Dict[str, Any]]:
    for bucket in ("tp_set", "fp_set", "fn_set"):
        folder = _GROUND_TRUTH / bucket
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            case = _load_case(path)
            case["_path"] = str(path)
            case["_bucket"] = bucket
            yield case


def _attachments_for(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rel in case.get("attachments") or []:
        path = (_ROOT / str(rel)).resolve()
        blob = path.read_bytes() if path.is_file() else bytes_for_legacy_fixture(path)
        rows.append(
            {
                "filename": path.name,
                "name": path.name,
                "content": blob,
                "fixture_authority": (
                    "local_untracked_sample"
                    if path.is_file()
                    else SYNTHETIC_AUTHORITY
                ),
            }
        )
    return rows


def evaluate_case(case: Dict[str, Any]) -> Dict[str, Any]:
    email = {
        "subject": case.get("subject") or case.get("id") or "benchmark case",
        "from_addr": case.get("from_addr") or "benchmark@example.test",
        "reply_to": case.get("reply_to") or case.get("from_addr") or "benchmark@example.test",
        "body": case.get("body") or "",
        "attachments": _attachments_for(case),
    }
    result = evaluate_email_security(email)
    security = result.get("security_analysis") if isinstance(result, dict) else {}
    return {
        "claim_scope": "synthetic_protocol_evaluation_not_provider_certification",
        "id": case.get("id"),
        "bucket": case.get("_bucket"),
        "path": case.get("_path"),
        "verdict_action": result.get("verdict_action"),
        "severity": result.get("severity"),
        "mitre_attack": list((security or {}).get("mitre_attack") or []),
        "possible_mitre_attack": list((security or {}).get("possible_mitre_attack") or []),
        "mitre_atlas": list((security or {}).get("mitre_atlas") or []),
        "possible_mitre_atlas": list((security or {}).get("possible_mitre_atlas") or []),
        "pasta_stage": (security or {}).get("validated_pasta_stage") or (security or {}).get("pasta_stage"),
        "evidence_quality": (security or {}).get("evidence_quality"),
        "raw": result,
    }


def run_benchmark() -> Dict[str, Any]:
    cases = list(iter_cases())
    results = [evaluate_case(case) for case in cases]
    tp = [r for r in results if r["bucket"] == "tp_set"]
    fp = [r for r in results if r["bucket"] == "fp_set"]
    fn = [r for r in results if r["bucket"] == "fn_set"]
    precision_proxy = sum(1 for r in tp if r["verdict_action"] == "security_review") / max(len(tp), 1)
    fp_leak_rate = sum(1 for r in fp if r["mitre_attack"]) / max(len(fp), 1)
    heuristic_band_rate = sum(
        1
        for r in results
        if isinstance(r.get("evidence_quality"), dict) and str(r["evidence_quality"].get("band") or "").upper() == "LOW"
    ) / max(len(results), 1)
    return {
        "claim_scope": "synthetic_protocol_evaluation_not_provider_certification",
        "case_count": len(results),
        "tp_count": len(tp),
        "fp_count": len(fp),
        "fn_count": len(fn),
        "precision_proxy": round(precision_proxy, 3),
        "false_positive_leak_rate": round(fp_leak_rate, 3),
        "heuristic_band_rate": round(heuristic_band_rate, 3),
        "results": results,
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
