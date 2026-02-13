#!/usr/bin/env python3
"""Seed a sample security_events row for local testing.
Usage: python scripts/seed_security_event.py --path /api/recommend --user test@example.com
"""
import argparse
import json
import uuid
from datetime import datetime
from src.app.models.db import db_session

parser = argparse.ArgumentParser()
parser.add_argument("--path", default="/api/v1/recommend/suggest")
parser.add_argument("--user", default="localtester")
parser.add_argument("--severity", default="high")
args = parser.parse_args()

payload = {
    "user": args.user,
    "user_query": "show me top 5 laptops in the range of 1200 to 2100 with at least 16 gb of ram",
}
analysis = {
    "sanitized": payload,
    "mitre_atlas": ["AML.T0043"],
    "owasp_llm_top10": ["LLM01:PromptInjection"],
    "signals": {"jailbreak": True, "unicode_obfuscation": False, "pii": False}
}

try:
    with db_session() as db:
        eid = str(uuid.uuid4())
        db.execute(
            "INSERT INTO security_events (id, event_time, path, severity, verdict_score, details) VALUES (:id, :et, :path, :severity, :score, :details)",
            {
                "id": eid,
                "et": datetime.utcnow().isoformat(),
                "path": args.path,
                "severity": args.severity,
                "score": 75,
                "details": json.dumps({"payload": payload, "analysis": analysis}, ensure_ascii=False),
            },
        )
        db.commit()
    print("Inserted security_event", eid)
except Exception as e:
    print("Error seeding event:", e)
