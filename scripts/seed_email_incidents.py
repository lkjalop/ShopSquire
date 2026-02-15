import argparse
import base64
import json
import os
import time
from typing import Dict, Any, List

import requests


def b64_file(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    return base64.b64encode(raw).decode("ascii")


def post_json(url: str, payload: Dict[str, Any], api_key: str | None = None, tenant_id: str | None = None) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    if tenant_id:
        headers["X-Tenant-Id"] = tenant_id
    r = requests.post(url, data=json.dumps(payload), headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def scenario_legit_supplier(tenant: str) -> Dict[str, Any]:
    return {
        "tenant_id": tenant,
        "message_id": f"legit-{int(time.time())}",
        "from_addr": "Accounts <accounts@ingrammicro.com.au>",
        "reply_to": "accounts@ingrammicro.com.au",
        "subject": "Invoice and stock update",
        "body": "Standard supplier update; no changes to banking.",
        "attachments": [],
        "spf_result": "pass",
        "dkim_result": "pass",
        "dmarc_result": "pass",
        "dmarc_policy": "reject",
        "external_sender": True,
        "vendor_domain": "ingrammicro.com.au",
        "dmarc_fail": False,
    }


def scenario_compromised_homoglyph(tenant: str, invoice_path: str) -> Dict[str, Any]:
    # Cyrillic 'а' (U+0430) in "fake"
    homoglyph_domain = "ingramfаke.com.au"
    b64 = b64_file(invoice_path)
    return {
        "tenant_id": tenant,
        "message_id": f"homoglyph-{int(time.time())}",
        "from_addr": f"George McDufus <accounts@{homoglyph_domain}>",
        "reply_to": f"accounts@{homoglyph_domain}",
        "subject": "[Accounts] New laptop stock | Ingram Fake",
        "body": (
            "We are changing our payment procedures and updated payment details. "
            "Please update remittance; disregard previous instructions."
        ),
        "attachments": [
            {
                "name": "INV-2026-00847.md",
                "content_type": "text/markdown",
                "content_b64": b64,
            }
        ],
        "spf_result": "fail",
        "dkim_result": "fail",
        "dmarc_result": "fail",
        "dmarc_policy": "reject",
        "external_sender": True,
        "vendor_domain": "ingrammicro.com.au",
        "bank_fingerprint": "bank-old-demo",
        "proposed_bank_fingerprint": "bank-new-demo",
        "dmarc_fail": True,
    }


def scenario_supplier_bank_change(tenant: str) -> Dict[str, Any]:
    return {
        "tenant_id": tenant,
        "message_id": f"bank-change-{int(time.time())}",
        "from_addr": "accounts@supplier.com",
        "reply_to": "accounts@supplier.com",
        "subject": "Supplier remittance update",
        "body": "Please update bank account and send payment to new beneficiary immediately.",
        "attachments": [],
        "spf_result": "pass",
        "dkim_result": "pass",
        "dmarc_result": "pass",
        "dmarc_policy": "reject",
        "external_sender": True,
        "vendor_domain": "supplier.com",
        "bank_fingerprint": "bank-old-demo",
        "proposed_bank_fingerprint": "bank-new-demo",
        "reply_chain_id": "thread-new",
        "prior_reply_chain_id": "thread-old",
        "dmarc_fail": False,
    }


def scenario_lolbin_fileless(tenant: str) -> Dict[str, Any]:
    body = (
        "Please run powershell -enc SQBFAFIAOgAgAC0AdwAgAGgAaQBkAGQAZQBu to fix deployment. "
        "Also visit https://evil-payments.example/login for confirmation."
    )
    return {
        "tenant_id": tenant,
        "message_id": f"lolbin-{int(time.time())}",
        "from_addr": "ops@trusted-supplier.com",
        "reply_to": "ops@trusted-supplier.com",
        "subject": "Operational fix needed",
        "body": body,
        "attachments": [
            {"name": "Fix.lnk", "content_type": "application/x-ms-shortcut", "content_b64": base64.b64encode(b"dummy").decode("ascii")}
        ],
        "spf_result": "pass",
        "dkim_result": "neutral",
        "dmarc_result": "pass",
        "dmarc_policy": "reject",
        "external_sender": True,
        "vendor_domain": "trusted-supplier.com",
        "dmarc_fail": False,
    }


def scenario_c2_beacon_text(tenant: str) -> Dict[str, Any]:
    body = "Beaconing to callback server at fixed polling interval; C2 instructions attached."
    return {
        "tenant_id": tenant,
        "message_id": f"c2-text-{int(time.time())}",
        "from_addr": "agent@partner.com",
        "reply_to": "agent@partner.com",
        "subject": "Heartbeat ping",
        "body": body,
        "attachments": [],
        "spf_result": "pass",
        "dkim_result": "pass",
        "dmarc_result": "pass",
        "dmarc_policy": "reject",
        "external_sender": True,
        "vendor_domain": "partner.com",
        "dmarc_fail": False,
    }


SCENARIOS = {
    "legit_supplier": scenario_legit_supplier,
    "compromised_homoglyph": scenario_compromised_homoglyph,
    "supplier_bank_change": scenario_supplier_bank_change,
    "lolbin_fileless": scenario_lolbin_fileless,
    "c2_beacon_text": scenario_c2_beacon_text,
}


def run(api: str, tenant: str, scenarios: List[str], api_key: str | None, invoice_path: str | None):
    url = api.rstrip("/") + "/api/v1/email_security/evaluate"
    for s in scenarios:
        fn = SCENARIOS.get(s)
        if not fn:
            print(f"[skip] unknown scenario: {s}")
            continue
        if s == "compromised_homoglyph" and not invoice_path:
            invoice_path = os.path.join("data", "demo", "invoices", "ingramFake_invoice.md")
        payload = fn(tenant, invoice_path) if s == "compromised_homoglyph" else fn(tenant)
        try:
            out = post_json(url, payload, api_key=api_key, tenant_id=tenant)
            print(f"[ok] {s}: severity={out.get('severity')} route={out.get('route')} reasons={out.get('reasons')[:5]}")
        except Exception as e:
            print(f"[error] {s}: {e}")


def main():
    p = argparse.ArgumentParser(description="Seed email incidents into ShopSquire Email XDR")
    p.add_argument("--api", default=os.getenv("API_URL", "http://127.0.0.1:8081"))
    p.add_argument("--tenant", default=os.getenv("TENANT_ID", "t-demo"))
    p.add_argument("--api-key", default=os.getenv("API_KEY", "local-owner-key"))
    p.add_argument("--invoice-path", default=None)
    p.add_argument(
        "--scenarios",
        nargs="*",
        default=[
            "legit_supplier",
            "compromised_homoglyph",
            "supplier_bank_change",
            "lolbin_fileless",
            "c2_beacon_text",
        ],
        help="Scenario names to seed",
    )
    args = p.parse_args()
    run(args.api, args.tenant, args.scenarios, api_key=args.api_key, invoice_path=args.invoice_path)


if __name__ == "__main__":
    main()
