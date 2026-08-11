"""Exercise fail-closed pilot identity matching and the immediate off rollback switch."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

REPO_ROOT = str(Path(__file__).resolve().parents[1])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.app.services.recommendation_facade import _in_pilot_cohort, _resolve_mode  # noqa: E402


def main() -> int:
    output = Path("tmp/pilot_rollback_certification.json")
    previous_mode = os.getenv("RECOMMEND_CORE_MODE")
    previous_subjects = os.getenv("RECOMMEND_CORE_PILOT_SUBJECTS")
    try:
        os.environ["RECOMMEND_CORE_MODE"] = "pilot"
        os.environ["RECOMMEND_CORE_PILOT_SUBJECTS"] = "cert-tenant:cert-user"
        pilot_mode = _resolve_mode()[0]
        exact_subject_included = _in_pilot_cohort("cert-tenant:cert-user")
        wrong_tenant_excluded = not _in_pilot_cohort("other-tenant:cert-user")
        bare_subject_excluded = not _in_pilot_cohort("cert-user")
        os.environ["RECOMMEND_CORE_MODE"] = "off"
        rollback_mode = _resolve_mode()[0]
        passed = all((
            pilot_mode == "pilot",
            exact_subject_included,
            wrong_tenant_excluded,
            bare_subject_excluded,
            rollback_mode == "off",
        ))
        artifact = {
            "schema_version": "pilot-rollback-cert-v1",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "identity_scope": "ephemeral_nonproduction_certification_identity",
            "real_pilot_identity_configured": False,
            "pilot_mode_observed": pilot_mode,
            "exact_tenant_subject_included": exact_subject_included,
            "wrong_tenant_excluded": wrong_tenant_excluded,
            "bare_subject_excluded": bare_subject_excluded,
            "rollback_mode_observed": rollback_mode,
            "passed": passed,
        }
    finally:
        if previous_mode is None:
            os.environ.pop("RECOMMEND_CORE_MODE", None)
        else:
            os.environ["RECOMMEND_CORE_MODE"] = previous_mode
        if previous_subjects is None:
            os.environ.pop("RECOMMEND_CORE_PILOT_SUBJECTS", None)
        else:
            os.environ["RECOMMEND_CORE_PILOT_SUBJECTS"] = previous_subjects
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": artifact["passed"],
        "real_pilot_identity_configured": False,
        "rollback_mode_observed": artifact["rollback_mode_observed"],
        "output": str(output),
    }, indent=2))
    return 0 if artifact["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
