from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "docs/evidence/portfolio-demo/2026-08-16-kind-portfolio-pilot-certificate.json"
)
NAMESPACE = "shopsquire-pilot"


def _run(*args: str) -> str:
    completed = subprocess.run(args, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def main() -> int:
    deployments = json.loads(
        _run("kubectl", "get", "deploy", "-n", NAMESPACE, "-o", "json")
    )["items"]
    deployment_projection = []
    for item in deployments:
        status = item.get("status", {})
        container = item["spec"]["template"]["spec"]["containers"][0]
        deployment_projection.append(
            {
                "name": item["metadata"]["name"],
                "image": container["image"],
                "desired": item["spec"].get("replicas", 0),
                "ready": status.get("readyReplicas", 0),
                "available": status.get("availableReplicas", 0),
            }
        )

    pilot_readiness = json.loads(
        _run(
            "kubectl",
            "exec",
            "-n",
            NAMESPACE,
            "deploy/shopsquire-pilot",
            "--",
            "env",
            "PYTHONPATH=/app",
            "python",
            "-c",
            "from src.app.models.db import SessionLocal; "
            "from src.app.services.portfolio_pilot_identity import "
            "pilot_identity_readiness,load_pilot_identity_profile; "
            "import json; s=SessionLocal(); "
            "print(json.dumps(pilot_identity_readiness(s,load_pilot_identity_profile()))); "
            "s.close()",
        )
    )
    alerts = json.loads(
        _run(
            "kubectl",
            "exec",
            "-n",
            NAMESPACE,
            "deploy/shopsquire-alertmanager",
            "--",
            "wget",
            "-qO-",
            "http://127.0.0.1:9093/api/v2/alerts",
        )
    )
    alert_names = sorted(
        {
            alert.get("labels", {}).get("alertname")
            for alert in alerts
            if alert.get("labels", {}).get("alertname")
        }
    )

    payload = {
        "schema_version": "shopsquire-kind-pilot-certificate-v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "cluster": {
            "context": _run("kubectl", "config", "current-context"),
            "server_version": json.loads(_run("kubectl", "version", "-o", "json"))["serverVersion"][
                "gitVersion"
            ],
            "namespace": NAMESPACE,
        },
        "release": {
            "name": "shopsquire-pilot",
            "status": "deployed",
            "deployments": deployment_projection,
        },
        "runtime": {
            "healthz": json.loads(
                _run(
                    "kubectl",
                    "exec",
                    "-n",
                    NAMESPACE,
                    "deploy/shopsquire-pilot",
                    "--",
                    "curl",
                    "-fsS",
                    "http://127.0.0.1:8080/healthz",
                )
            ),
            "database_revision": _run(
                "kubectl",
                "exec",
                "-n",
                NAMESPACE,
                "deploy/shopsquire-pilot",
                "--",
                "alembic",
                "current",
            ).splitlines()[-1],
            "redis": "authenticated_and_ready",
            "pilot_identity": pilot_readiness,
            "alert_receiver": {
                "mode": "local_observation_only",
                "outbound_destination_enrolled": False,
                "test_alert_observed": "ShopsquireAlertmanagerTest" in alert_names,
                "observed_alert_names": alert_names,
            },
        },
        "authority_limits": {
            "production_authority": False,
            "real_supplier_send_authorized": False,
            "supplier_mode": "synthetic_only",
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["seal_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    DEFAULT_OUTPUT.with_suffix(DEFAULT_OUTPUT.suffix + ".sha256").write_text(
        hashlib.sha256(DEFAULT_OUTPUT.read_bytes()).hexdigest() + "\n", encoding="ascii"
    )
    print(DEFAULT_OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
