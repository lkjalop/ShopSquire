import json
import logging
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Optional

from src.app.observability.metrics import (
    record_webhook_delivery,
    record_webhook_delivery_failure,
    record_webhook_delivery_retry,
    record_webhook_delivery_dlq,
)

from src.app.models.db import get_engine
from sqlalchemy import text
from src.app.security.url_guard import ensure_safe_outbound_url

try:
    import requests
except Exception:
    requests = None


def _ensure_table(engine):
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    payload TEXT,
                    tenant_id TEXT,
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 5,
                    next_attempt_at TEXT,
                    status TEXT DEFAULT 'pending',
                    last_error TEXT,
                    key_id TEXT,
                    secret_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
                )
            )
    except Exception:
        pass


def enqueue_webhook(id: str, url: str, payload: dict, secret: Optional[str] = None, key_id: Optional[str] = None, max_attempts: int = 5, tenant_id: Optional[str] = None) -> None:
    eng = get_engine()
    try:
        ensure_safe_outbound_url(url)
        _ensure_table(eng)
        with eng.begin() as conn:
            conn.execute(
                text("INSERT INTO webhook_deliveries (id, url, payload, tenant_id, attempts, max_attempts, next_attempt_at, status, key_id, secret_id) VALUES (:id, :url, :payload, :tenant_id, 0, :max_attempts, :next_at, 'pending', :key_id, :secret_id)"),
                {
                    "id": id,
                    "url": url,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "tenant_id": tenant_id,
                    "max_attempts": int(max_attempts or 5),
                    "next_at": datetime.utcnow().isoformat(),
                    "key_id": key_id,
                    "secret_id": "env" if secret else None,
                },
            )
            try:
                record_webhook_delivery(url)
            except Exception:
                pass
    except Exception:
        # Best-effort fallback: immediate send if DB enqueue fails (bounded 2s timeout — not a hang).
        try:
            if requests and payload is not None:
                ensure_safe_outbound_url(url)
                requests.post(url, json=payload, timeout=2)
        except Exception as exc:
            # observable, not a silent swallow — a dropped webhook should leave a trail.
            import logging
            logging.getLogger(__name__).warning("webhook immediate-send fallback failed for %s: %s", url, exc)


def _deliver_row(row):
    # Row format (after SELECT):
    # id, url, payload, tenant_id, attempts, max_attempts, next_attempt_at, status, last_error, key_id, secret_id
    id = row[0]
    url = row[1]
    payload_text = row[2]
    tenant_id = row[3] if len(row) > 3 else None
    attempts = int(row[4] or 0)
    max_attempts = int(row[5] or 5)
    key_id = row[9] if len(row) > 9 else None
    secret_id = row[10] if len(row) > 10 else None
    try:
        payload = json.loads(payload_text) if payload_text else {}
    except Exception:
        payload = {}
    start = time.time()
    try:
        ensure_safe_outbound_url(url)
        if not requests:
            raise RuntimeError("requests unavailable")
        resp = requests.post(url, json=payload, timeout=10)
        latency = time.time() - start
        from src.app.observability.metrics import record_webhook_delivery_success
        if 200 <= resp.status_code < 300:
            try:
                record_webhook_delivery_success(url, tenant_id, latency)
            except Exception:
                pass
            logging.getLogger(__name__).info("webhook delivered: %s status=%s id=%s", url, resp.status_code, id)
            return True, None
        else:
            logging.getLogger(__name__).warning("webhook delivery non-2xx: %s status=%s id=%s", url, resp.status_code, id)
            return False, f"status_{resp.status_code}:{resp.text[:200]}"
    except Exception as exc:
        tb = traceback.format_exc()
        try:
            latency = time.time() - start
            from src.app.observability.metrics import record_webhook_delivery_failure

            record_webhook_delivery_failure(url)
        except Exception:
            pass
        return False, str(exc) + "\n" + tb


def _worker_loop(stop_event, poll_interval=0.5):
    eng = get_engine()
    _ensure_table(eng)
    logger = logging.getLogger(__name__)
    logger.info("webhook dispatcher starting; poll_interval=%s", poll_interval)
    while not stop_event.is_set():
        try:
            now = datetime.utcnow().isoformat()
            with eng.begin() as conn:
                rows = conn.execute(
                    text("SELECT id, url, payload, tenant_id, attempts, max_attempts, next_attempt_at, status, last_error, key_id, secret_id FROM webhook_deliveries WHERE status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= :now) ORDER BY created_at ASC LIMIT 20"),
                    {"now": now},
                ).fetchall()
            logger.debug("dispatcher fetched %d pending rows", len(rows))
            if not rows:
                stop_event.wait(poll_interval)
                continue
            for r in rows:
                rid = r[0]
                ok, err = _deliver_row(r)
                logger.debug("dispatcher delivered id=%s ok=%s err=%s", rid, ok, (err or ""))
                try:
                    with eng.begin() as conn:
                        if ok:
                            conn.execute(text("UPDATE webhook_deliveries SET status = 'sent', last_error = NULL WHERE id = :id"), {"id": rid})
                            logger.info("dispatcher marked sent id=%s", rid)
                        else:
                            attempts = int(r[4] or 0) + 1
                            if attempts >= int(r[5] or 5):
                                conn.execute(text("UPDATE webhook_deliveries SET status = 'dlq', attempts = :a, last_error = :e WHERE id = :id"), {"a": attempts, "e": str(err)[:2000], "id": rid})
                                try:
                                    record_webhook_delivery_dlq(r[1])
                                except Exception:
                                    pass
                                logger.warning("dispatcher moved id=%s to DLQ after %s attempts", rid, attempts)
                            else:
                                backoff = min(60 * 60, (2 ** attempts))
                                next_at = (datetime.utcnow() + timedelta(seconds=backoff)).isoformat()
                                conn.execute(text("UPDATE webhook_deliveries SET attempts = :a, next_attempt_at = :n, last_error = :e WHERE id = :id"), {"a": attempts, "n": next_at, "e": str(err)[:2000], "id": rid})
                                try:
                                    record_webhook_delivery_retry(r[1])
                                except Exception:
                                    pass
                                try:
                                    record_webhook_delivery_failure(r[1])
                                except Exception:
                                    pass
                                logger.info("dispatcher scheduled retry id=%s attempts=%s next_at=%s", rid, attempts, next_at)
                except Exception:
                    logger.exception("error updating delivery row %s", rid)
        except Exception:
            logger.exception("error in dispatcher loop")
    logger.info("webhook dispatcher stopping")


_worker_thread = None
_stop_event = None


def start_worker(app=None, poll_interval: float = 0.2):
    global _worker_thread, _stop_event
    if _worker_thread and _worker_thread.is_alive():
        return _worker_thread
    _stop_event = threading.Event()
    _worker_thread = threading.Thread(target=_worker_loop, args=(_stop_event, poll_interval), daemon=True)
    _worker_thread.start()
    return _worker_thread


def stop_worker():
    global _worker_thread, _stop_event
    try:
        if _stop_event:
            _stop_event.set()
        if _worker_thread:
            _worker_thread.join(timeout=2.0)
    except Exception:
        pass
