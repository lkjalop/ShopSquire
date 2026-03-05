from __future__ import annotations

from typing import Dict, List
from src.app.services.decision_log import log_decision


class NotificationService:
    TEMPLATES = {
        "case_created": {
            "email_subject": "We've received your case #{case_id}",
            "sms": "Case #{case_id} received. We'll review within 24hrs. Track: {track_url}",
        },
        "analysis_complete": {
            "email_subject": "Update on your case #{case_id}",
            "sms": "Case #{case_id} update: {ai_summary}. Next step: {next_action}",
        },
        "return_label_ready": {
            "email_subject": "Your return label is ready - Case #{case_id}",
            "sms": "Return label ready for case #{case_id}. Check email or: {label_url}",
        },
    }

    async def send_notification(self, event: str, context: Dict, channels: List[str] = ["email"]) -> None:
        tpl = self.TEMPLATES.get(event)
        if not tpl:
            return
        # Persist a bitemporal decision log for notification dispatch intent
        try:
            tenant = context.get("tenant_id") if isinstance(context, dict) else None
            log_decision(
                agent_name="notification_agent",
                input_data={
                    "event": event,
                    "channels": channels,
                    "customer_tier": context.get("customer_tier"),
                },
                retrieved_context={"context": context, "customer_tier": context.get("customer_tier")},
                proposed_action={"dispatch": True},
                agent_reasoning="notification dispatch",
                policy_version="v1",
                approval_required=False,
                execution_status="executed",
                tenant_id=tenant,
            )
        except Exception:
            pass
        for ch in channels:
            if ch == "email" and context.get("customer_email"):
                await self._send_email(context["customer_email"], tpl["email_subject"].format(**context), self._render_email(event, context))
            elif ch == "sms" and context.get("customer_phone"):
                await self._send_sms(context["customer_phone"], tpl["sms"].format(**context))

    async def _send_email(self, to: str, subject: str, body: str) -> None:
        # Optional SES integration controlled via env; falls back to no-op
        import os
        try:
            if os.getenv("AWS_SES_ENABLED", "0").lower() not in ("1", "true", "yes"):
                return None
            sender = os.getenv("AWS_SES_SENDER", None)
            region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
            if not sender:
                return None
            import boto3
            client = boto3.client("ses", region_name=region)
            client.send_email(
                Source=sender,
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject},
                    "Body": {"Text": {"Data": body}},
                },
            )
        except Exception:
            # Gracefully ignore send errors in demo/testing environments
            return None

    async def _send_sms(self, to: str, body: str) -> None:
        import os
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_FROM_NUMBER")
        if not (account_sid and auth_token and from_number):
            return None
        try:
            from twilio.rest import Client as TwilioClient
            client = TwilioClient(account_sid, auth_token)
            client.messages.create(to=to, from_=from_number, body=body[:1600])
        except ImportError:
            # twilio package not installed — log and skip rather than crash
            import logging
            logging.getLogger("shopsquire.notifications").warning("twilio package not installed; SMS skipped")
        except Exception:
            pass

    def _render_email(self, event: str, ctx: Dict) -> str:
        # Minimal plaintext body
        return f"Event: {event}\nContext: {ctx}"
