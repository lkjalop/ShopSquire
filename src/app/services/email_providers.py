import os
import re
from typing import Dict, Any
from src.app.services.safe_links import create_safe_link
from src.app.services.outbound_email_monitor import record_outbound_email_event, analyze_agent_outbound_email, store_outbound_anomaly


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
            analysis = analyze_agent_outbound_email(agent_id=agent_id, minutes=int(os.getenv("OUTBOUND_MONITOR_WINDOW_MIN", "60") or 60))
            store_outbound_anomaly(tenant_id=tenant_id, agent_id=agent_id, event_id=str(ev.get("id") or ""), analysis=analysis, severity=("high" if analysis.get("anomalous") else "info"))
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
            import boto3
            client = boto3.client(
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
