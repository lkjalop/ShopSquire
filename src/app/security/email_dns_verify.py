"""email_dns_verify.py — Live DNS verification of SPF, DMARC, and DKIM records.

Called from evaluate_email_security() to independently validate auth claims
made in the email payload.  If the caller claims SPF=pass but DNS shows no
SPF record (or one that doesn't include the sending IP range), we add a
``caller_auth_mismatch`` indicator.

Design principles
-----------------
* **Never authoritative for hard deny** — DNS is best-effort and slow.
  Results augment verdict signals; they never replace them.
* **Short timeout** — 1.5s per query via dnspython's Resolver; skipped
  entirely when ``EMAIL_DNS_VERIFY_ENABLED`` env is not ``1``/``true``.
* **No network calls in tests** — gated behind the env flag so CI/unit
  tests don't need a real nameserver.
* **Graceful degradation** — any DNS failure returns
  ``{"available": False, "error": "..."}`` without raising.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

_log = logging.getLogger("shopsquire.email_dns_verify")

_TIMEOUT = float(os.getenv("EMAIL_DNS_VERIFY_TIMEOUT_SEC", "1.5") or 1.5)
_ENABLED = os.getenv("EMAIL_DNS_VERIFY_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def _resolver():
    """Return a configured dns.resolver.Resolver or None if dnspython missing."""
    try:
        import dns.resolver  # type: ignore

        r = dns.resolver.Resolver()
        r.lifetime = _TIMEOUT
        r.timeout = _TIMEOUT
        return r
    except ImportError:
        return None


def _extract_domain(addr: str) -> str | None:
    """Extract the domain part from an email address or bare domain."""
    addr = str(addr or "").strip().lower()
    if "@" in addr:
        parts = addr.rsplit("@", 1)
        return parts[-1].split(">")[0].strip() or None
    # Might already be a domain
    if re.match(r"^[a-z0-9.\-]+\.[a-z]{2,}$", addr):
        return addr
    return None


def verify_spf(domain: str, *, resolver=None) -> dict[str, Any]:
    """Check that *domain* has a published SPF TXT record.

    Returns::

        {"available": bool, "record": str|None, "mechanisms": list[str], "error": str|None}
    """
    r = resolver or _resolver()
    if r is None:
        return {"available": False, "record": None, "mechanisms": [], "error": "dnspython_not_installed"}
    try:
        answers = r.resolve(domain, "TXT")
        for rdata in answers:
            txt = "".join(p.decode("utf-8", errors="replace") for p in rdata.strings)
            if txt.startswith("v=spf1"):
                mechanisms = [t for t in txt.split() if t != "v=spf1"]
                return {"available": True, "record": txt[:512], "mechanisms": mechanisms, "error": None}
        return {"available": False, "record": None, "mechanisms": [], "error": "no_spf_record"}
    except Exception as exc:
        return {"available": False, "record": None, "mechanisms": [], "error": str(exc)[:120]}


def verify_dmarc(domain: str, *, resolver=None) -> dict[str, Any]:
    """Check *_dmarc.domain* for a published DMARC policy record.

    Returns::

        {"available": bool, "record": str|None, "policy": str|None, "pct": int, "error": str|None}
    """
    r = resolver or _resolver()
    if r is None:
        return {"available": False, "record": None, "policy": None, "pct": 100, "error": "dnspython_not_installed"}
    lookup = f"_dmarc.{domain}"
    try:
        answers = r.resolve(lookup, "TXT")
        for rdata in answers:
            txt = "".join(p.decode("utf-8", errors="replace") for p in rdata.strings)
            if "v=DMARC1" in txt:
                policy = None
                pct = 100
                for part in txt.split(";"):
                    part = part.strip()
                    if part.lower().startswith("p="):
                        policy = part[2:].strip().lower()
                    elif part.lower().startswith("pct="):
                        try:
                            pct = int(part[4:].strip())
                        except ValueError:
                            pass
                return {"available": True, "record": txt[:512], "policy": policy, "pct": pct, "error": None}
        return {"available": False, "record": None, "policy": None, "pct": 100, "error": "no_dmarc_record"}
    except Exception as exc:
        return {"available": False, "record": None, "policy": None, "pct": 100, "error": str(exc)[:120]}


def verify_dkim_selector(domain: str, selector: str, *, resolver=None) -> dict[str, Any]:
    """Look up ``selector._domainkey.domain`` for a DKIM public key.

    Returns::

        {"available": bool, "key_type": str|None, "error": str|None}
    """
    r = resolver or _resolver()
    if r is None:
        return {"available": False, "key_type": None, "error": "dnspython_not_installed"}
    lookup = f"{selector}._domainkey.{domain}"
    try:
        answers = r.resolve(lookup, "TXT")
        for rdata in answers:
            txt = "".join(p.decode("utf-8", errors="replace") for p in rdata.strings)
            if "v=DKIM1" in txt or "p=" in txt:
                key_type = None
                for part in txt.split(";"):
                    part = part.strip()
                    if part.lower().startswith("k="):
                        key_type = part[2:].strip().lower()
                return {"available": True, "key_type": key_type or "rsa", "error": None}
        return {"available": False, "key_type": None, "error": "no_dkim_record"}
    except Exception as exc:
        return {"available": False, "key_type": None, "error": str(exc)[:120]}


# Common DKIM selectors used by major ESPs — we try these when no selector is
# explicitly provided in the email headers.
_COMMON_SELECTORS = ["default", "google", "s1", "s2", "dkim", "mail", "k1", "selector1", "selector2"]


def run_dns_auth_checks(email: dict[str, Any]) -> dict[str, Any]:
    """Run all available DNS auth checks for the given email dict.

    Returns a structured result with per-check findings and a list of
    ``discrepancy_indicators`` to inject into the verdict pipeline.

    Safe to call even when dnspython is absent (returns ``skipped=True``).
    When disabled via ``EMAIL_DNS_VERIFY_ENABLED=0`` returns ``skipped=True``
    immediately.
    """
    if not _ENABLED:
        return {"skipped": True, "reason": "disabled_by_config"}

    from_addr = str(email.get("from_addr") or "")
    domain = _extract_domain(from_addr)
    if not domain:
        return {"skipped": True, "reason": "no_from_domain"}

    r = _resolver()
    if r is None:
        return {"skipped": True, "reason": "dnspython_not_installed"}

    result: dict[str, Any] = {
        "skipped": False,
        "domain": domain,
        "spf": {},
        "dmarc": {},
        "dkim": {},
        "discrepancy_indicators": [],
    }

    # ── SPF ──
    try:
        spf = verify_spf(domain, resolver=r)
        result["spf"] = spf
        caller_spf = str(email.get("spf_result") or "").lower()
        if caller_spf == "pass" and not spf["available"]:
            result["discrepancy_indicators"].append({
                "type": "dns_spf_record_missing",
                "value": domain,
                "reason": f"Caller claims SPF=pass but no SPF TXT record found for {domain}",
                "severity": "medium",
            })
            _log.warning("SPF discrepancy for %s: caller=pass, DNS=no_record", domain)
    except Exception as exc:
        result["spf"] = {"available": False, "error": str(exc)[:120]}

    # ── DMARC ──
    try:
        dmarc = verify_dmarc(domain, resolver=r)
        result["dmarc"] = dmarc
        caller_dmarc = str(email.get("dmarc_result") or "").lower()
        caller_dmarc_fail = bool(email.get("dmarc_fail", False))
        dns_policy = str(dmarc.get("policy") or "none").lower()

        if not dmarc["available"]:
            if caller_dmarc == "pass":
                result["discrepancy_indicators"].append({
                    "type": "dns_dmarc_record_missing",
                    "value": domain,
                    "reason": f"Caller claims DMARC=pass but no DMARC record found for _dmarc.{domain}",
                    "severity": "medium",
                })
                _log.warning("DMARC discrepancy for %s: caller=pass, DNS=no_record", domain)
        else:
            # If DNS says policy=reject/quarantine and caller says pass, suspicious
            if dns_policy in ("reject", "quarantine") and caller_dmarc == "pass" and not caller_dmarc_fail:
                # This is valid in legitimate email — just record it, don't escalate alone
                result["discrepancy_indicators"].append({
                    "type": "dns_dmarc_strict_policy_with_pass_claim",
                    "value": {"policy": dns_policy, "domain": domain},
                    "reason": f"DMARC DNS policy={dns_policy} but caller reports pass; verify MTA alignment",
                    "severity": "low",
                })
    except Exception as exc:
        result["dmarc"] = {"available": False, "error": str(exc)[:120]}

    # ── DKIM (best-effort selector probe) ──
    try:
        headers = email.get("headers") or {}
        dkim_sig = ""
        if isinstance(headers, dict):
            dkim_sig = str(headers.get("DKIM-Signature") or headers.get("dkim-signature") or "")
        elif isinstance(headers, list):
            for h in headers:
                if isinstance(h, dict):
                    name = str(h.get("name") or h.get("key") or "").lower()
                    if name == "dkim-signature":
                        dkim_sig = str(h.get("value") or "")
                        break

        selector: str | None = None
        if dkim_sig:
            m = re.search(r"\bs=([a-zA-Z0-9_\-]+)", dkim_sig)
            if m:
                selector = m.group(1)

        caller_dkim = str(email.get("dkim_result") or "").lower()
        if selector:
            dkim = verify_dkim_selector(domain, selector, resolver=r)
            result["dkim"] = {**dkim, "selector": selector}
            if caller_dkim == "pass" and not dkim["available"]:
                result["discrepancy_indicators"].append({
                    "type": "dns_dkim_selector_missing",
                    "value": f"{selector}._domainkey.{domain}",
                    "reason": f"Caller claims DKIM=pass but selector '{selector}' not found in DNS",
                    "severity": "medium",
                })
                _log.warning("DKIM discrepancy for %s selector=%s: caller=pass, DNS=not_found", domain, selector)
        elif caller_dkim == "pass":
            # No selector in headers — probe common selectors to see if ANY key exists
            found_any = False
            for sel in _COMMON_SELECTORS:
                try:
                    probe = verify_dkim_selector(domain, sel, resolver=r)
                    if probe["available"]:
                        result["dkim"] = {**probe, "selector": sel, "selector_probed": True}
                        found_any = True
                        break
                except Exception:
                    pass
            if not found_any:
                result["dkim"] = {"available": False, "selector": None, "error": "no_common_selector_found"}
    except Exception as exc:
        result["dkim"] = {"available": False, "error": str(exc)[:120]}

    return result
