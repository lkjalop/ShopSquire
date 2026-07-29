import os
import re
from typing import Dict, Any
from src.app.services.safe_links import create_safe_link
from src.app.services.outbound_email_monitor import record_outbound_email_event, analyze_agent_outbound_email, store_outbound_anomaly
from src.app.services.agent_containment import contain_agent, is_contained


_URL_PAT = re.compile(r"https?://[^\s<>()\"']+")


def _rewrite_safe_links(body: str, *, tenant_id: str | None = None, campaign_id: str | None = None) -> str:
    if str(os.getenv("SAFE_LINK_REWRITE_ENABLED", "0")).lower() not in ("1", "true", "yes"):
        return body
    txt = str(body or "")
    urls = list(dict.fromkeys([m.group(0) for m in _URL_PAT.finditer(txt)]))
    if not urls:
        return txt
    out = txt
    for u in urls[:50]:
        try:
            sl = create_safe_link(tenant_id=tenant_id, original_url=u, campaign_id=campaign_id)
            su = str(sl.get("safe_url") or "")
            if su:
                out = out.replace(u, su)
        except Exception:
            continue
    return out


class BaseEmailProvider:
    name = "base-email"

    def send(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError()


class SendGridProvider(BaseEmailProvider):
    name = "sendgrid"

    def __init__(self):
        self.api_key = os.getenv("SENDGRID_API_KEY")
        self.endpoint = os.getenv("SENDGRID_API_URL", "https://api.sendgrid.com/v3/mail/send")

    def send(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        body = _rewrite_safe_links(
            body,
            tenant_id=(str(kwargs.get("tenant_id")) if kwargs.get("tenant_id") is not None else None),
            campaign_id=(str(kwargs.get("campaign_id")) if kwargs.get("campaign_id") is not None else None),
        )
        # Outbound monitoring is best-effort and non-blocking.
        try:
            agent_id = str(kwargs.get("agent_id") or "Email_Send_Agent")
            tenant_id = str(kwargs.get("tenant_id")) if kwargs.get("tenant_id") is not None else None
            thread_id = str(kwargs.get("thread_id")) if kwargs.get("thread_id") is not None else None
            decision_id = str(kwargs.get("decision_id")) if kwargs.get("decision_id") is not None else None
            if is_contained(agent_id=agent_id, capability="email_send"):
                return {"ok": False, "blocked": True, "error": "agent_contained", "agent_id": agent_id, "capability": "email_send"}
            ev = record_outbound_email_event(
                tenant_id=tenant_id,
                agent_id=agent_id,
                to=to,
                subject=subject,
                body=body,
                thread_id=thread_id,
                decision_id=decision_id,
                meta={"provider": "sendgrid"},
            )
            # Outbound content DLP ENFORCEMENT: a SECRET leaving the boundary is blocked outright
            # (unambiguous). PII is flagged in the event but not blocked by default (legit mail
            # carries names/phones). OUTBOUND_DLP_BLOCK_PII=1 hardens it to block PII too.
            _dlp = (ev or {}).get("dlp") or {}
            _dlp_block = bool(_dlp.get("action") == "block") or (
                _dlp.get("action") == "review"
                and str(os.getenv("OUTBOUND_DLP_BLOCK_PII", "0")).strip().lower() in ("1", "true", "yes", "on")
            )
            # A released item (owner judged the flag a false positive) BYPASSES the block once.
            if _dlp_block and not kwargs.get("_dlp_release"):
                _qid = None
                try:
                    from src.app.services.outbound_dlp_quarantine import quarantine_blocked_send
                    _qid = quarantine_blocked_send(tenant_id=tenant_id, agent_id=agent_id, to=to,
                                                   subject=subject, body=body, dlp=_dlp)
                except Exception:
                    _qid = None
                return {"ok": False, "blocked": True, "error": "dlp_content_block",
                        "agent_id": agent_id, "capability": "email_send", "dlp": _dlp,
                        "quarantine_id": _qid,
                        "release_via": (f"/api/v1/email/outbound/quarantine/{_qid}/release" if _qid else None)}
            analysis = analyze_agent_outbound_email(agent_id=agent_id, minutes=int(os.getenv("OUTBOUND_MONITOR_WINDOW_MIN", "60") or 60))
            store_outbound_anomaly(tenant_id=tenant_id, agent_id=agent_id, event_id=str(ev.get("id") or ""), analysis=analysis, severity=("high" if analysis.get("anomalous") else "info"))
            try:
                thr = float(os.getenv("OUTBOUND_CONTAINMENT_SCORE_THRESHOLD", "0.75") or 0.75)
            except Exception:
                thr = 0.75
            if analysis.get("anomalous") and float(analysis.get("score") or 0.0) >= thr:
                # Contain both sending and tool execution to demonstrate enforcement.
                contain_agent(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    capability="email_send",
                    score=float(analysis.get("score") or 0.0),
                    reasons=list(analysis.get("reasons") or []),
                    actor="Outbound_Comms_Monitor",
                    decision_id=decision_id,
                    trace_id=decision_id,
                    ttl_seconds=int(os.getenv("OUTBOUND_CONTAINMENT_TTL_SEC", "3600") or 3600),
                )
                contain_agent(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    capability="tool_run",
                    score=float(analysis.get("score") or 0.0),
                    reasons=list(analysis.get("reasons") or []),
                    actor="Outbound_Comms_Monitor",
                    decision_id=decision_id,
                    trace_id=decision_id,
                    ttl_seconds=int(os.getenv("OUTBOUND_CONTAINMENT_TTL_SEC", "3600") or 3600),
                )
        except Exception:
            pass
        if not self.api_key:
            # dev fallback: write to local file
            try:
                with open("dump/email_dev.log", "a", encoding="utf-8") as f:
                    f.write(f"TO: {to}\nSUBJECT: {subject}\nBODY: {body}\n----\n")
                return {"ok": True, "dev": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        try:
            import requests
            payload = {
                "personalizations": [{"to": [{"email": to}]}],
                "from": {"email": kwargs.get("from_email", "noreply@shopsquire.local")},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            }
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=10)
            return {"ok": resp.status_code < 300, "status_code": resp.status_code, "text": resp.text}
        except Exception as e:
            return {"ok": False, "error": str(e)}


class SESProvider(BaseEmailProvider):
    name = "ses"

    def __init__(self):
        self.enabled = bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))

    def send(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        body = _rewrite_safe_links(
            body,
            tenant_id=(str(kwargs.get("tenant_id")) if kwargs.get("tenant_id") is not None else None),
            campaign_id=(str(kwargs.get("campaign_id")) if kwargs.get("campaign_id") is not None else None),
        )
        try:
            agent_id = str(kwargs.get("agent_id") or "Email_Send_Agent")
            tenant_id = str(kwargs.get("tenant_id")) if kwargs.get("tenant_id") is not None else None
            thread_id = str(kwargs.get("thread_id")) if kwargs.get("thread_id") is not None else None
            decision_id = str(kwargs.get("decision_id")) if kwargs.get("decision_id") is not None else None
            if is_contained(agent_id=agent_id, capability="email_send"):
                return {"ok": False, "blocked": True, "error": "agent_contained", "agent_id": agent_id, "capability": "email_send"}
            ev = record_outbound_email_event(
                tenant_id=tenant_id,
                agent_id=agent_id,
                to=to,
                subject=subject,
                body=body,
                thread_id=thread_id,
                decision_id=decision_id,
                meta={"provider": "ses"},
            )
            analysis = analyze_agent_outbound_email(agent_id=agent_id, minutes=int(os.getenv("OUTBOUND_MONITOR_WINDOW_MIN", "60") or 60))
            store_outbound_anomaly(tenant_id=tenant_id, agent_id=agent_id, event_id=str(ev.get("id") or ""), analysis=analysis, severity=("high" if analysis.get("anomalous") else "info"))
            try:
                thr = float(os.getenv("OUTBOUND_CONTAINMENT_SCORE_THRESHOLD", "0.75") or 0.75)
            except Exception:
                thr = 0.75
            if analysis.get("anomalous") and float(analysis.get("score") or 0.0) >= thr:
                contain_agent(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    capability="email_send",
                    score=float(analysis.get("score") or 0.0),
                    reasons=list(analysis.get("reasons") or []),
                    actor="Outbound_Comms_Monitor",
                    decision_id=decision_id,
                    trace_id=decision_id,
                    ttl_seconds=int(os.getenv("OUTBOUND_CONTAINMENT_TTL_SEC", "3600") or 3600),
                )
                contain_agent(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    capability="tool_run",
                    score=float(analysis.get("score") or 0.0),
                    reasons=list(analysis.get("reasons") or []),
                    actor="Outbound_Comms_Monitor",
                    decision_id=decision_id,
                    trace_id=decision_id,
                    ttl_seconds=int(os.getenv("OUTBOUND_CONTAINMENT_TTL_SEC", "3600") or 3600),
                )
        except Exception:
            pass
        if not self.enabled:
            try:
                with open("dump/email_dev.log", "a", encoding="utf-8") as f:
                    f.write(f"SES-TO: {to}\nSUBJECT: {subject}\nBODY: {body}\n----\n")
                return {"ok": True, "dev": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        try:
            from src.app.providers.aws import get_client

            client = get_client(
                "ses",
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                region_name=os.getenv("AWS_REGION"),
            )
            resp = client.send_email(
                Source=kwargs.get("from_email", "noreply@shopsquire.local"),
                Destination={"ToAddresses": [to]},
                Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
            )
            return {"ok": True, "raw": resp}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def get_default_email_provider():
    # prefer SendGrid then SES then dev fallback
    sg = SendGridProvider()
    if sg.api_key:
        return sg
    ses = SESProvider()
    if ses.enabled:
        return ses
    return sg
