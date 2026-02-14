import json
import os
from pathlib import Path
from typing import Dict, List


def _run_email_mutations() -> List[Dict]:
    from src.app.security.email_security import evaluate_email_security
    cases = [
        {
            "name": "display_name_spoof",
            "email": {
                "message_id": "<rt-display@shopsquire>",
                "from_addr": "CEO <ceo@micros0ft.com>",
                "reply_to": "finance@evil-payments.example",
                "subject": "Urgent wire",
                "body": "Please wire ASAP",
            },
            "expect": {"route": "security_review"},
        },
        {
            "name": "lolbin_powershell",
            "email": {
                "message_id": "<rt-lolbin@shopsquire>",
                "from_addr": "Ops <ops@supplier.com>",
                "reply_to": "ops@supplier.com",
                "subject": "Update",
                "body": "Run powershell -enc AAA",
            },
            "expect": {"route": "human_review"},
        },
    ]
    out: List[Dict] = []
    for c in cases:
        v = evaluate_email_security(c["email"], tenant_id="t-redteam")
        out.append({"case": c["name"], "severity": v.get("severity"), "route": v.get("route")})
    return out


def _run_c2_mutations() -> List[Dict]:
    from src.app.services import outbound_email_monitor as oem
    # Minimal beacon-like timing
    t0 = 1_700_100_000
    agent = "agent-red"
    times = [t0 + i * 60 for i in range(6)]
    for i, ts in enumerate(times):
        oem.record_outbound_email_event(
            tenant_id="t-red",
            agent_id=agent,
            to=f"u{i}@ex.com",
            subject=f"Ping {i}",
            body="hb",
            now_ts=int(ts),
        )
    a = oem.analyze_agent_outbound_email(agent_id=agent, minutes=60, now_ts=int(times[-1]))
    return [{"events": a.get("events"), "anomalous": a.get("anomalous"), "reasons": a.get("reasons")}]


def run(*, out_path: str | None = None) -> Dict[str, List[Dict]]:
    report = {
        "email": _run_email_mutations(),
        "c2": _run_c2_mutations(),
    }
    if out_path:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    print(json.dumps(run(out_path="tmp/redteam_report.json"), indent=2))
