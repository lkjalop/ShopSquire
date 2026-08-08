"""Measure three real Ollama shadow narrations without granting buyer authority."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import requests

REPO_ROOT = str(Path(__file__).resolve().parents[1])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.app.services.recommendation_core.workload_decision import (  # noqa: E402
    FitLedgerRow,
    ProductConfigurationIdentity,
    WorkloadContract,
    configuration_hash,
    reduce_workload_decision,
)
from src.app.services.recommendation_core.workload_narration_shadow import (  # noqa: E402
    run_shadow_narration,
)


def _decision() -> dict:
    specs = {"cpu_model": "certification-cpu", "ram_gb": 32}
    product = ProductConfigurationIdentity(
        sku="SHADOW-CERT-001",
        identifier_type="manufacturer_part_number",
        identifier="SHADOW-CERT-MPN",
        configuration_hash=configuration_hash(sku="SHADOW-CERT-001", specs=specs, form_factor="laptop"),
        form_factor="laptop",
    )
    workload = WorkloadContract(
        desired_outcome="Run the named simulation in its documented supported configuration",
        artefact_name="Shadow certification simulation",
        artefact_version="current",
        execution_shape="local",
        surviving_hypothesis_ids=["shadow-certification"],
    )
    row = FitLedgerRow(
        attribute_key="platform_support",
        attribute_label="Documented platform support",
        required=[["equals", "supported"]],
        required_text="supported",
        observed="supported",
        observed_text="supported",
        verdict="meets_minimum",
        verification_status="verified",
        claim_class="attested",
        requirement_claim_ids=["req-shadow-cert"],
        capability_claim_ids=["cap-shadow-cert"],
        artefact_name=workload.artefact_name,
        artefact_version=workload.artefact_version,
        freshness_status="fresh",
    )
    return reduce_workload_decision(workload=workload, product=product, rows=[row]).model_dump(mode="json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3:14b")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit-ms", type=int, default=8000)
    parser.add_argument("--output", default="tmp/workload_narration_shadow_certification.json")
    args = parser.parse_args()
    decision = _decision()

    def generate(prompt: str) -> str:
        response = requests.post(
            args.url.rstrip("/") + "/api/generate",
            json={
                "model": args.model,
                "prompt": prompt + "\n/no_think",
                "stream": False,
                "think": False,
                "keep_alive": "10m",
                "options": {"temperature": 0, "num_predict": 120},
            },
            timeout=max(30.0, args.limit_ms / 1000 * 3),
        )
        response.raise_for_status()
        return str(response.json().get("response") or "")

    warm_started = time.perf_counter()
    requests.post(
        args.url.rstrip("/") + "/api/generate",
        json={"model": args.model, "prompt": "Reply ready. /no_think", "stream": False, "think": False,
              "keep_alive": "10m", "options": {"temperature": 0, "num_predict": 8}},
        timeout=90,
    ).raise_for_status()
    warm_ms = int((time.perf_counter() - warm_started) * 1000)

    results = []
    for index in range(max(3, args.runs)):
        result = run_shadow_narration(decision, generate=generate, model_id=args.model)
        result["run"] = index + 1
        result["under_limit"] = result["elapsed_ms"] < args.limit_ms
        results.append(result)
    passed = all(item["status"] == "accepted_shadow" and item["under_limit"] for item in results)
    artifact = {
        "schema_version": "workload-narration-shadow-cert-v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "provider": "ollama",
        "model": args.model,
        "buyer_visible": False,
        "commercial_authority_granted": False,
        "warmup_ms_excluded": warm_ms,
        "latency_limit_ms": args.limit_ms,
        "runs": results,
        "three_consecutive_under_limit": passed,
        "passed": passed,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": passed,
        "warmup_ms_excluded": warm_ms,
        "run_elapsed_ms": [item["elapsed_ms"] for item in results],
        "run_statuses": [item["status"] for item in results],
        "output": str(output),
    }, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
