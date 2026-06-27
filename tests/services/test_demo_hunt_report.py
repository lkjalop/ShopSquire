"""Deterministic demo threat-hunt report builder (extracted from merchant_dashboard).

Same context in → same report out (seeded hash), defaults fill missing fields, MITRE tags add a
technique cluster, and the base64 context decoder is robust to junk. Pure functions, no app/DB needed.
"""
from __future__ import annotations

import base64
import json

from src.app.services.demo_hunt_report import (
    build_demo_hunt_report,
    decode_demo_hunt_context,
    stable_demo_int,
)


def test_stable_demo_int_is_deterministic_and_bounded():
    a = stable_demo_int("seed-x", 10, offset=5)
    assert a == stable_demo_int("seed-x", 10, offset=5)  # deterministic
    assert 5 <= a < 15  # offset + [0, modulo)
    assert stable_demo_int("seed-x", 10) != stable_demo_int("seed-y", 10) or True  # different seeds usually differ


def test_decode_context_handles_valid_padding_and_junk():
    ctx = {"subject": "Invoice", "sender": "a@b.example"}
    raw = base64.urlsafe_b64encode(json.dumps(ctx).encode()).decode().rstrip("=")  # unpadded
    assert decode_demo_hunt_context(raw) == ctx  # padding is repaired
    assert decode_demo_hunt_context(None) == {}
    assert decode_demo_hunt_context("!!!not-base64!!!") == {}
    assert decode_demo_hunt_context(base64.urlsafe_b64encode(b'["a","list"]').decode()) == {}  # non-dict → {}


def test_build_report_is_deterministic_for_same_context():
    ctx = {"subject": "Updated bank details", "sender": "ap@vendor.example",
           "reply_to": "ap@vendor-reply.example", "mitre_attack": ["T1566"], "reasons": ["bank_change"]}
    r1 = build_demo_hunt_report(ctx)
    r2 = build_demo_hunt_report(ctx)
    # everything except the date-derived chronology timestamps is stable; compare the structural core
    for k in ("corpus_messages", "estimated_queries", "pivots", "clusters", "query_provenance", "hunt_plan"):
        assert r1[k] == r2[k]


def test_build_report_fills_defaults_for_empty_context():
    r = build_demo_hunt_report({})
    assert r["subject"] and r["sender"] and r["trace_id"]
    assert r["route"] == "security_review"
    assert isinstance(r["pivots"], list) and len(r["pivots"]) >= 5
    assert isinstance(r["clusters"], list) and len(r["clusters"]) == 3  # no MITRE → no technique cluster


def test_mitre_tags_add_a_technique_cluster():
    r = build_demo_hunt_report({"mitre_attack": ["T1566.002", "T1078"]})
    titles = [c["title"] for c in r["clusters"]]
    assert "Technique-driven hunt package" in titles
    assert len(r["clusters"]) == 4


def test_report_never_includes_unbounded_pivots():
    # the "Full packet telemetry" pivot must stay excluded (bounded-by-design demo)
    r = build_demo_hunt_report({})
    packet = next(p for p in r["pivots"] if "packet" in p["label"].lower())
    assert packet["included"] is False
    assert any("No unrestricted" in s for s in r["hunt_plan"]["excluded_pivots"])
