import json
import threading
import logging
import os
import time
import hashlib
import hmac
from src.app.security.url_guard import ensure_safe_outbound_url

try:
    import requests
except Exception:
    requests = None

logger = logging.getLogger(__name__)


def _make_signature(secret: str, payload_bytes: bytes, ts: int) -> str:
    basestring = f"{ts}.".encode("utf-8") + payload_bytes
    return hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()


def send_webhook(url: str, payload: dict, timeout: float = 0.5, secret: str | None = None, key_id: str | None = None) -> None:
    """Send webhook in background, best-effort, non-blocking.

    If `secret` is provided, signs the payload using HMAC-SHA256 with a timestamp
    and sets headers expected by `WebhookSecurityMiddleware` (x-webhook-signature,
    x-webhook-timestamp). Optionally include `x-webhook-key` to identify the key.
    """

    def _post():
        try:
            ensure_safe_outbound_url(url)
        except Exception as exc:
            logger.warning("webhook blocked by url guard for %s: %s", url, exc)
            return
        # If persistent delivery is enabled, enqueue and return immediately
        try:
            if str(os.getenv("PERSISTENT_WEBHOOKS", "0")).lower() in ("1", "true", "yes"):
                try:
                    import uuid
                    from src.app.services.webhook_dispatcher import enqueue_webhook

                    enqueue_webhook(str(uuid.uuid4()), url, payload, secret=secret, key_id=key_id)
                    return
                except Exception:
                    # fall through to best-effort send if enqueue fails
                    pass
        except Exception:
            pass

        if not requests:
            logger.debug("requests not available; webhook skipped for %s", url)
            return
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            ts = int(time.time())
            # allow explicit secret override; fallback to env var
            effective_secret = secret or os.getenv("WEBHOOK_SECRET", "")
            if effective_secret:
                sig = _make_signature(effective_secret, body, ts)
                headers[os.getenv("WEBHOOK_SIGNATURE_HEADER", "x-webhook-signature")] = f"sha256={sig}"
                headers[os.getenv("WEBHOOK_TIMESTAMP_HEADER", "x-webhook-timestamp")] = str(ts)
                if key_id:
                    headers["x-webhook-key"] = key_id

            requests.post(url, data=body, headers=headers, timeout=timeout)
        except Exception as e:
            logger.debug("webhook send failed: %s", e)

    t = threading.Thread(target=_post, daemon=True)
    t.start()


def parse_senders(config_path: str, section: str) -> list:
    """Load senders from a yaml/json file under `webhooks`.

    Sender entries may be either a URL string or a dict {url, secret, key_id}.
    Returns a list of dicts with keys: url, secret, key_id.
    """
    out = []
    try:
        from pathlib import Path

        cfg_text = Path(config_path).read_text()
        try:
            import yaml as _yaml

            cfg = _yaml.safe_load(cfg_text)
        except Exception:
            try:
                cfg = json.loads(cfg_text)
            except Exception:
                cfg = {}
        items = (cfg.get("webhooks", {}) or {}).get(section, []) or []
        for it in items:
            if isinstance(it, str):
                out.append({"url": it, "secret": None, "key_id": None})
            elif isinstance(it, dict):
                out.append({"url": it.get("url"), "secret": it.get("secret"), "key_id": it.get("key_id")})
    except Exception:
        pass
    return out
