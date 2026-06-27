"""Deterministic demo threat-hunt report builder (extracted from merchant_dashboard).

Pure functions: a decoded context dict in → a structured, DETERMINISTIC hunt report out (stable across
runs via a seeded hash, so the demo page renders identically). No request/HTML/DB dependencies, so the
logic is unit-testable in isolation and the router stays thin. This is SYNTHETIC demo content (clearly
labelled as such on the page); it never touches real telemetry.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any


def decode_demo_hunt_context(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        padded = str(raw).strip()
        padded += "=" * (-len(padded) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="ignore")
        parsed = json.loads(decoded)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def stable_demo_int(seed: str, modulo: int, *, offset: int = 0) -> int:
    digest = hashlib.sha256(str(seed).encode("utf-8", errors="ignore")).hexdigest()
    return offset + (int(digest[:8], 16) % max(modulo, 1))


def build_demo_hunt_report(ctx: dict[str, Any]) -> dict[str, Any]:
    subject = str(ctx.get("subject") or "Updated Payment Details").strip() or "Updated Payment Details"
    sender = str(ctx.get("sender") or "accounts@balashnikovai.com.au").strip() or "accounts@balashnikovai.com.au"
    reply_to = str(ctx.get("reply_to") or sender).strip() or sender
    trace_id = str(ctx.get("trace_id") or "trace-demo-email-hunt").strip() or "trace-demo-email-hunt"
    severity = str(ctx.get("severity") or "warning").strip() or "warning"
    verdict = str(ctx.get("verdict_action") or "security_review").strip() or "security_review"
    route = str(ctx.get("route") or "security_review").strip() or "security_review"
    reasons = [str(x).strip() for x in (ctx.get("reasons") or []) if str(x).strip()]
    mitre = [str(x).strip() for x in (ctx.get("mitre_attack") or []) if str(x).strip()]
    attachments = [str(x).strip() for x in (ctx.get("attachments") or []) if str(x).strip()]
    geo_country = str(ctx.get("geo_country") or "AU").strip() or "AU"
    asn = str(ctx.get("asn") or "AS13335").strip() or "AS13335"
    asn_org = str(ctx.get("asn_org") or "Cloudflare").strip() or "Cloudflare"
    reply_mismatch = bool(ctx.get("reply_domain_mismatch"))
    related_incidents = int(ctx.get("related_incident_count") or 0)
    confidence = str(ctx.get("risk_band") or "high").strip() or "high"
    seed = "|".join([trace_id, subject, sender, reply_to, ",".join(reasons), ",".join(mitre), asn, geo_country])

    corpus_messages = stable_demo_int(seed + ":messages", 120, offset=205)
    corpus_identities = stable_demo_int(seed + ":ids", 18, offset=26)
    corpus_suppliers = stable_demo_int(seed + ":suppliers", 8, offset=9)
    corpus_days = stable_demo_int(seed + ":days", 90, offset=275)
    matched_messages = stable_demo_int(seed + ":matched", 7, offset=5)
    impacted_users = stable_demo_int(seed + ":users", 5, offset=2)
    impacted_suppliers = stable_demo_int(seed + ":vendors", 4, offset=1)
    estimated_minutes = stable_demo_int(seed + ":minutes", 7, offset=3)
    estimated_queries = stable_demo_int(seed + ":queries", 12, offset=14)
    approval_level = "tier-1 analyst approval" if confidence in ("low", "medium") else "tier-1 analyst plus owner review for sensitive pivots"
    domain = sender.split("@", 1)[-1] if "@" in sender else sender
    reply_domain = reply_to.split("@", 1)[-1] if "@" in reply_to else reply_to
    shared_domains = [domain]
    if reply_domain and reply_domain not in shared_domains:
        shared_domains.append(reply_domain)
    url_domain = f"portal.{domain}" if domain else "portal.example.com"
    bank_ref = f"BSB 012-4{stable_demo_int(seed + ':bsb', 10)}6 / Acct 8877{stable_demo_int(seed + ':acct', 9000, offset=1000)}"
    supplier_key = f"supplier::{domain}"
    account_key = f"identity::{sender}"
    attachment_hashes = [
        hashlib.sha256(f"{seed}:{name}".encode("utf-8", errors="ignore")).hexdigest()[:16]
        for name in attachments[:3]
    ]
    pivots = [
        {"label": "Sender", "value": sender, "why": "Primary identity asserted by the message.", "included": True},
        {"label": "Reply-To", "value": reply_to, "why": "Used to detect reply-path drift or impersonation.", "included": True},
        {"label": "Return-Path", "value": f"bounce@{reply_domain or domain}", "why": "Checked for delivery-path consistency.", "included": True},
        {"label": "Subject lineage", "value": subject, "why": "Used to correlate repeated payment or urgency themes.", "included": True},
        {"label": "Domains", "value": ", ".join(shared_domains), "why": "Domain overlap is a reliable clustering pivot.", "included": True},
        {"label": "URLs", "value": f"https://{url_domain}/payment-update", "why": "Synthetic hunt pivots on linked infrastructure and portals.", "included": True},
        {"label": "Attachment hashes/names", "value": ", ".join([f"{name} [{digest}]" for name, digest in zip(attachments[:3], attachment_hashes)] or ["No attachment in scope"]), "why": "Attachments often recur across supplier-fraud campaigns.", "included": True},
        {"label": "Bank details / remittance strings", "value": bank_ref, "why": "Payment-change fraud often reuses beneficiary details or BSB/account fragments.", "included": True},
        {"label": "ASN / GeoIP", "value": f"{asn} / {asn_org} / {geo_country}", "why": "Infrastructure reuse is useful when domains rotate.", "included": True},
        {"label": "Related supplier / account IDs", "value": f"{supplier_key}, {account_key}", "why": "Separates impersonation from compromised-account hypotheses.", "included": True},
        {"label": "Full packet telemetry", "value": "Not connected in this demo tenant", "why": "Deeper network hunts stay disabled unless the connector and approvals exist.", "included": False},
    ]
    selected_sources = [
        {"name": "Email telemetry", "scope": "Synthetic seeded corpus", "query_count": 5, "why": "Primary source for sender, subject, attachment, and delivery-path correlation."},
        {"name": "Secure email gateway", "scope": "Synthetic SEG events", "query_count": 3, "why": "Used for verdict history, header anomalies, and click telemetry."},
        {"name": "SIEM/XDR", "scope": "Synthetic correlation records", "query_count": 2, "why": "Used to detect incident overlap and downstream touchpoints."},
        {"name": "Identity / IAM", "scope": "Synthetic user and supplier identities", "query_count": 2, "why": "Used to compare approved contacts, compromised-account hints, and trust relationships."},
        {"name": "Supplier trust / internal case history", "scope": "Synthetic governance records", "query_count": 2, "why": "Used to compare supplier baselines and prior incidents."},
    ]
    optional_sources = [
        {"name": "DNS / proxy", "status": "available if connected", "why": "Useful for shared destination or click overlap."},
        {"name": "CASB / DLP", "status": "available if connected", "why": "Useful for SaaS identity overlap or sensitive sharing signals."},
        {"name": "EDR", "status": "available if connected", "why": "Useful for host-level execution or user interaction evidence."},
        {"name": "Packet / full host telemetry", "status": "not enabled in demo", "why": "High-friction telemetry should stay role-gated and connector-bounded."},
    ]
    excluded_pivots = [
        "No broad internet reconnaissance was performed.",
        "No unrestricted tenant-wide search was performed.",
        "No host or packet pivots were used because those connectors are not enabled in this synthetic demo.",
    ]
    hunt_plan = {
        "time_window": f"Last {corpus_days} days of seeded synthetic telemetry",
        "sources_selected": selected_sources,
        "sources_optional": optional_sources,
        "estimated_cost": f"{estimated_queries} bounded queries / about {estimated_minutes} minutes",
        "approval_level": approval_level,
        "why_generated": "The current email contains payment-change and supplier-trust signals that justify a bounded correlation hunt.",
        "excluded_pivots": excluded_pivots,
    }
    confidence_model = {
        "evidence_confidence": {"score": stable_demo_int(seed + ":ev_conf", 16, offset=80), "label": "high", "why": "The seed email contains strong direct indicators such as payment-change language, supplier-trust drift, and attachment context."},
        "correlation_confidence": {"score": stable_demo_int(seed + ":corr_conf", 22, offset=68), "label": "medium-high", "why": "Multiple synthetic records overlap on sender infrastructure, wording, and supplier context."},
        "operational_confidence": {"score": stable_demo_int(seed + ":op_conf", 20, offset=62), "label": "medium", "why": "Correlation is strong enough to investigate, but downstream containment still requires human verification."},
    }
    query_provenance = [
        {
            "finding": "Sender infrastructure overlap",
            "source": "Email telemetry",
            "query": f"sender:{sender} OR reply_to:{reply_to} OR return_path:bounce@{reply_domain or domain}",
            "matched_fields": ["sender", "reply_to", "return_path", "received_asn"],
            "time_range": hunt_plan["time_window"],
            "result_count": matched_messages,
        },
        {
            "finding": "Supplier payment-change cluster",
            "source": "Secure email gateway",
            "query": f"subject:\"{subject}\" OR attachment:{attachments[0] if attachments else 'payment_form'} OR bank_ref:\"{bank_ref}\"",
            "matched_fields": ["subject", "attachment_name", "body_bank_details", "policy_route"],
            "time_range": hunt_plan["time_window"],
            "result_count": max(matched_messages - 1, 2),
        },
        {
            "finding": "Identity and trust relationship review",
            "source": "Identity / IAM + supplier history",
            "query": f"supplier_key:{supplier_key} OR account:{account_key}",
            "matched_fields": ["supplier_key", "approved_contact_path", "identity_status", "incident_refs"],
            "time_range": hunt_plan["time_window"],
            "result_count": impacted_users + impacted_suppliers,
        },
    ]
    negative_evidence = [
        "No repeated delivery overlap was found outside the sender / reply / ASN cluster.",
        "No confirmed benign approved-contact path explains the new remittance request in the seeded corpus.",
        "No broad identity anomaly was found across unrelated suppliers; the signals stay narrow to this supplier lane.",
    ]
    guardrails = {
        "would_weaken": [
            "Approved supplier contact path matches the new banking request out of band.",
            "No repeat bank details, attachment fingerprints, or sender infrastructure overlap is found in connected sources.",
            "A known benign supplier template update explains the wording drift.",
        ],
        "would_confirm": [
            "The same bank details or reply domain appear in other supplier-fraud cases.",
            "Connected SIEM/XDR shows the same sender infrastructure touching other users or suppliers.",
            "Approved-contact records show the sender identity is not authorized to request trust or remittance changes.",
        ],
        "requires_human": [
            "Verify supplier details using an existing trusted contact path.",
            "Approve any downstream containment or external push.",
            "Review whether the message reflects impersonation, compromised account, or a legitimate business exception.",
        ],
    }
    audit_trail = [
        f"Input evidence captured from trace {trace_id}.",
        f"Generated {len([p for p in pivots if p['included']])} evidence-scoped pivots and excluded unrestricted searches.",
        f"Executed {estimated_queries} bounded synthetic queries across {len(selected_sources)} approved source groups.",
        "Clustered results into infrastructure, payment-lure, and identity-impact hypotheses.",
        "Returned structured findings, negative evidence, and guardrails before narrative summary.",
        "Awaits analyst decision for any downstream action outside the synthetic corpus.",
    ]

    base_date = datetime.now(timezone.utc) - timedelta(days=corpus_days)
    chronology = []
    for idx in range(6):
        days = stable_demo_int(f"{seed}:day:{idx}", max(corpus_days - 5, 10), offset=idx * 3)
        chronology.append(
            {
                "ts": (base_date + timedelta(days=days)).strftime("%Y-%m-%d"),
                "event": [
                    "Synthetic supplier-remittance lure observed",
                    "Reply-domain mismatch clustered with supplier lane",
                    "Shared ASN / hosting footprint linked to message set",
                    "Payment-detail change request matched prior wording",
                    "Synthetic identity review flagged possible impersonation path",
                    "Analyst-approved hunt package prepared for downstream systems",
                ][idx],
            }
        )

    clusters = [
        {
            "title": "Sender infrastructure overlap",
            "confidence": "high" if related_incidents or reply_mismatch else "medium",
            "summary": f"{matched_messages} synthetic messages share {asn} / {asn_org} hosting or adjacent mail-routing infrastructure with this email.",
            "evidence": [
                f"Shared infrastructure pivot: {asn} ({asn_org})",
                f"Originating geo cluster: {geo_country}",
                f"Observed sender domains: {', '.join(shared_domains)}",
            ],
            "analyst_checks": [
                "Pivot on sender, reply, and return-path domains across the mail corpus.",
                "Group by ASN, hosting footprint, and GeoIP to identify repeated infrastructure reuse.",
                "Check whether the same supplier path or trust record was touched by earlier incidents.",
            ],
        },
        {
            "title": "Payment-change lure cluster",
            "confidence": "high" if any("bank" in r.lower() or "verification" in r.lower() for r in reasons) else "medium",
            "summary": f"Synthetic corpus shows repeated payment-detail / urgency wording across {matched_messages - 1 if matched_messages > 1 else 2} related messages over {corpus_days} days.",
            "evidence": [
                f"Subject lineage includes: {subject}",
                "Repeated urgency and trusted-supplier framing detected",
                "Attachment / bank-change themes cluster with supplier impersonation scenarios",
            ],
            "analyst_checks": [
                "Search for the same bank details, beneficiary names, or payment instructions across the synthetic email set.",
                "Check whether similar language preceded account-trust or supplier-change requests.",
                "Bundle matching subjects, reply domains, and attachment classes into one review package.",
            ],
        },
        {
            "title": "Account / identity impact review",
            "confidence": "medium",
            "summary": f"Hunt narrowed to {impacted_users} synthetic identities and {impacted_suppliers} supplier records for compromised-vs-impersonated account review.",
            "evidence": [
                f"Route at analysis time: {route}",
                f"Verdict at analysis time: {verdict}",
                f"Risk band at analysis time: {confidence}",
            ],
            "analyst_checks": [
                "Separate likely impersonation from likely compromised-account scenarios before containment.",
                "Check legitimate approved contacts versus newly observed identities or reply paths.",
                "Only escalate to stronger downstream response if overlap exists beyond this single message.",
            ],
        },
    ]

    if mitre:
        clusters.append(
            {
                "title": "Technique-driven hunt package",
                "confidence": "medium",
                "summary": "The synthetic hunt uses current MITRE tags to scope where to pivot next instead of running an unconstrained broad search.",
                "evidence": [f"Exact MITRE tags from current evidence: {', '.join(mitre)}"],
                "analyst_checks": [
                    "Use tag-aligned hunts in SIEM/XDR first.",
                    "Keep deeper host or network hunts gated behind explicit approval and telemetry availability.",
                ],
            }
        )

    downstream = [
        "Mail telemetry: sender, reply-to, return-path, subject, attachment class, beneficiary strings",
        "Identity / IAM: legitimate vs impersonated account review, supplier contact path verification",
        "SIEM / XDR: correlated incidents, user touchpoints, shared domains, ASN / GeoIP reuse",
        "Optional deeper sources if connected: eBPF, host triage, packet, DLP / CASB",
    ]
    production = [
        "Keep the hunt human-gated before any downstream containment or push.",
        "Use deterministic search packs generated from the evidence, not free-form autonomous scope creep.",
        "Start with mail, identity, and SIEM telemetry. Add host/network telemetry only if a tenant actually has it.",
        "Persist hunt runs, evidence pivots, and analyst outcomes for feedback and tuning.",
    ]

    return {
        "subject": subject,
        "sender": sender,
        "reply_to": reply_to,
        "trace_id": trace_id,
        "severity": severity,
        "verdict_action": verdict,
        "route": route,
        "reasons": reasons,
        "mitre_attack": mitre,
        "attachments": attachments,
        "geo_country": geo_country,
        "asn": asn,
        "asn_org": asn_org,
        "related_incidents": related_incidents,
        "corpus_messages": corpus_messages,
        "corpus_identities": corpus_identities,
        "corpus_suppliers": corpus_suppliers,
        "corpus_days": corpus_days,
        "estimated_minutes": estimated_minutes,
        "estimated_queries": estimated_queries,
        "pivots": pivots,
        "hunt_plan": hunt_plan,
        "query_provenance": query_provenance,
        "confidence_model": confidence_model,
        "negative_evidence": negative_evidence,
        "guardrails": guardrails,
        "audit_trail": audit_trail,
        "clusters": clusters,
        "chronology": chronology,
        "downstream": downstream,
        "production": production,
    }
