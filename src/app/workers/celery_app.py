from __future__ import annotations

import os
from celery import Celery
from kombu import Queue
from celery.schedules import crontab


def _setup_hmac_signing(celery: Celery) -> None:
    """Configure HMAC-based message content signing as lighter alternative to x509.

    Uses CELERY_HMAC_KEY env var. When set, task payloads are HMAC-SHA256 signed
    and verified on the worker side via a Celery signal handler.
    """
    hmac_key = os.getenv("CELERY_HMAC_KEY", "").strip()
    if not hmac_key:
        # No signing material available at all — use plain JSON
        celery.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")
        return

    # Store key in app config for signal handler access
    celery.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        _hmac_signing_key=hmac_key,
    )

    from celery.signals import before_task_publish, task_prerun
    import hashlib
    import hmac
    import json as _json

    def _canonical_envelope(*, task_name=None, task_id=None, args=None, kwargs=None) -> bytes:
        payload = {
            "task": str(task_name or ""),
            "id": str(task_id or ""),
            "args": list(args or []),
            "kwargs": dict(kwargs or {}),
        }
        return _json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()

    @before_task_publish.connect
    def _sign_task(headers=None, body=None, **kwargs):
        """Attach HMAC signature to task headers before publishing."""
        key = celery.conf.get("_hmac_signing_key", "")
        if not key or not body:
            return
        hdrs = headers or {}
        b_args = []
        b_kwargs = {}
        try:
            if isinstance(body, (list, tuple)) and len(body) >= 2:
                b_args = body[0] or []
                b_kwargs = body[1] or {}
        except Exception:
            pass
        payload = _canonical_envelope(
            task_name=hdrs.get("task"),
            task_id=hdrs.get("id"),
            args=b_args,
            kwargs=b_kwargs,
        )
        sig = hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()
        if headers is not None:
            headers["x-hmac-signature"] = sig

    @task_prerun.connect
    def _verify_task(task=None, args=None, kwargs=None, **kw):
        """Verify HMAC signature on worker side before executing task."""
        key = celery.conf.get("_hmac_signing_key", "")
        if not key:
            return
        request = getattr(task, "request", None)
        if request is None:
            return
        # Celery stores custom headers on the request object
        headers = getattr(request, "headers", None) or {}
        provided_sig = headers.get("x-hmac-signature") if isinstance(headers, dict) else None
        if not provided_sig:
            # No signature = unsigned task — reject in strict mode
            import logging
            logging.getLogger("celery_hmac").warning(
                "Unsigned task rejected: %s", getattr(task, "name", "unknown")
            )
            raise RuntimeError("Task message missing HMAC signature — possible injection")

        req_args = getattr(request, "args", args) or []
        req_kwargs = getattr(request, "kwargs", kwargs) or {}
        computed = hmac.new(
            key.encode(),
            _canonical_envelope(
                task_name=getattr(task, "name", ""),
                task_id=getattr(request, "id", ""),
                args=req_args,
                kwargs=req_kwargs,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(str(provided_sig), computed):
            import logging
            logging.getLogger("celery_hmac").error(
                "Task signature mismatch rejected: %s", getattr(task, "name", "unknown")
            )
            raise RuntimeError("Task HMAC signature mismatch — possible tampering")


def make_celery(app_name: str = "shopsquire") -> Celery:
    broker = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0"))
    backend = os.getenv("CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://redis:6379/1"))
    qprefix = str(os.getenv("CELERY_QUEUE_PREFIX", "shopsquire") or "shopsquire").strip()
    default_q = f"{qprefix}.default"
    swarm_q = f"{qprefix}.swarm"
    celery = Celery(app_name, broker=broker, backend=backend)

    # M07: Default to signing-enabled in production environments.
    # In production, unsigned task messages can be injected by compromised Redis.
    _env = str(os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "local")) or "local").strip().lower()
    _default_signing = "1" if _env in ("production", "prod", "staging") else "0"
    signing_enabled = str(os.getenv("CELERY_TASK_SIGNING_ENABLED", _default_signing)).lower() in ("1", "true", "yes")
    if signing_enabled:
        key = str(os.getenv("CELERY_SECURITY_KEY", "") or "").strip()
        cert = str(os.getenv("CELERY_SECURITY_CERTIFICATE", "") or "").strip()
        store = str(os.getenv("CELERY_SECURITY_CERT_STORE", "") or "").strip()
        if key and cert and store:
            celery.conf.update(
                task_serializer="auth",
                accept_content=["auth"],
                result_serializer="json",
                event_serializer="json",
                security_key=key,
                security_certificate=cert,
                security_cert_store=store,
                security_digest="sha256",
            )
            try:
                celery.setup_security()
            except Exception:
                import logging
                logging.getLogger("celery_app").warning(
                    "Celery task signing setup failed — invalid cert material. "
                    "Falling back to HMAC content signing."
                )
                _setup_hmac_signing(celery)
        else:
            if _env in ("production", "prod", "staging"):
                import logging
                logging.getLogger("celery_app").warning(
                    "CELERY_TASK_SIGNING_ENABLED=1 in production but no cert material provided. "
                    "Set CELERY_SECURITY_KEY, CELERY_SECURITY_CERTIFICATE, CELERY_SECURITY_CERT_STORE. "
                    "Using HMAC content signing as fallback."
                )
            _setup_hmac_signing(celery)
    else:
        celery.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json")

    poll_enabled = str(os.getenv("SECURITY_CROWDSTRIKE_POLL_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    poll_min = max(1, min(60, int(float(os.getenv("SECURITY_CROWDSTRIKE_POLL_MINUTES", "5") or 5))))
    poll_tenant = str(os.getenv("SECURITY_CROWDSTRIKE_POLL_TENANT_ID", "default") or "default")
    poll_limit = max(1, min(500, int(float(os.getenv("SECURITY_CROWDSTRIKE_POLL_LIMIT", "100") or 100))))
    reco_cf_enabled = str(os.getenv("RECO_CF_NIGHTLY_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    reco_cf_hour = max(0, min(23, int(float(os.getenv("RECO_CF_NIGHTLY_HOUR_UTC", "2") or 2))))
    reco_cf_minute = max(0, min(59, int(float(os.getenv("RECO_CF_NIGHTLY_MINUTE_UTC", "15") or 15))))
    forecast_gov_enabled = str(os.getenv("FORECAST_GOVERNANCE_SNAPSHOT_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    forecast_gov_hour = max(0, min(23, int(float(os.getenv("FORECAST_GOVERNANCE_HOUR_UTC", "3") or 3))))
    forecast_gov_minute = max(0, min(59, int(float(os.getenv("FORECAST_GOVERNANCE_MINUTE_UTC", "10") or 10))))
    visual_refresh_enabled = str(os.getenv("VISUAL_SEARCH_REFRESH_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    visual_refresh_min = max(15, min(1440, int(float(os.getenv("VISUAL_SEARCH_REFRESH_MINUTES", "120") or 120))))
    risk_snapshot_enabled = str(os.getenv("RISK_REGISTER_SNAPSHOT_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    risk_snapshot_hour = max(0, min(23, int(float(os.getenv("RISK_REGISTER_SNAPSHOT_HOUR_UTC", "1") or 1))))
    risk_snapshot_minute = max(0, min(59, int(float(os.getenv("RISK_REGISTER_SNAPSHOT_MINUTE_UTC", "30") or 30))))
    incident_sla_enabled = str(os.getenv("INCIDENT_SLA_CELERY_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    incident_sla_min = max(1, min(60, int(float(os.getenv("INCIDENT_SLA_CELERY_MINUTES", "1") or 1))))
    trace_recovery_enabled = str(os.getenv("TRACE_BROKER_RECOVERY_CELERY_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    trace_recovery_min = max(1, min(60, int(float(os.getenv("TRACE_BROKER_RECOVERY_CELERY_MINUTES", "5") or 5))))
    catalog_reindex_enabled = str(os.getenv("CATALOG_REINDEX_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    catalog_reindex_hour = max(0, min(23, int(float(os.getenv("CATALOG_REINDEX_HOUR_UTC", "1") or 1))))
    catalog_reindex_minute = max(0, min(59, int(float(os.getenv("CATALOG_REINDEX_MINUTE_UTC", "0") or 0))))
    vuln_scan_sched_enabled = str(os.getenv("VULN_SCAN_SCHEDULED_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
    vuln_scan_sched_hour = max(0, min(23, int(float(os.getenv("VULN_SCAN_SCHEDULED_HOUR_UTC", "4") or 4))))
    vuln_scan_sched_minute = max(0, min(59, int(float(os.getenv("VULN_SCAN_SCHEDULED_MINUTE_UTC", "0") or 0))))
    anomaly_snapshot_enabled = str(os.getenv("ANOMALY_SNAPSHOT_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    anomaly_snapshot_min = max(15, min(120, int(float(os.getenv("ANOMALY_SNAPSHOT_INTERVAL_MIN", "60") or 60))))
    config_integrity_enabled = str(os.getenv("CONFIG_INTEGRITY_CHECK_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    config_integrity_min = max(1, min(60, int(float(os.getenv("CONFIG_INTEGRITY_CHECK_MINUTES", "5") or 5))))
    prompt_verify_enabled = str(os.getenv("PROMPT_HASH_VERIFY_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    prompt_verify_min = max(1, min(60, int(float(os.getenv("PROMPT_HASH_VERIFY_MINUTES", "5") or 5))))
    audit_chain_verify_enabled = str(os.getenv("AUDIT_CHAIN_VERIFY_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    audit_chain_verify_min = max(1, min(60, int(float(os.getenv("AUDIT_CHAIN_VERIFY_MINUTES", "5") or 5))))

    beat_schedule = {}
    if poll_enabled:
        beat_schedule["security-crowdstrike-poll"] = {
            "task": "src.app.tasks.security_poll_tasks.poll_crowdstrike",
            "schedule": crontab(minute=f"*/{poll_min}"),
            "args": (poll_tenant, poll_limit, poll_min),
        }
    if reco_cf_enabled:
        beat_schedule["recommend-cf-nightly-train"] = {
            "task": "src.app.tasks.model_ops_tasks.train_recommend_cf_nightly",
            "schedule": crontab(minute=str(reco_cf_minute), hour=str(reco_cf_hour)),
            "args": (),
        }
    if forecast_gov_enabled:
        beat_schedule["forecast-governance-snapshot"] = {
            "task": "src.app.tasks.model_ops_tasks.snapshot_forecast_governance",
            "schedule": crontab(minute=str(forecast_gov_minute), hour=str(forecast_gov_hour)),
            "args": (),
        }
    if visual_refresh_enabled:
        beat_schedule["visual-search-index-refresh"] = {
            "task": "src.app.tasks.model_ops_tasks.refresh_visual_search_index",
            "schedule": crontab(minute=f"*/{visual_refresh_min}"),
            "args": (),
        }
    if risk_snapshot_enabled:
        beat_schedule["risk-register-daily-snapshot"] = {
            "task": "src.app.tasks.model_ops_tasks.snapshot_risk_register_daily",
            "schedule": crontab(minute=str(risk_snapshot_minute), hour=str(risk_snapshot_hour)),
            "args": (),
        }
    if incident_sla_enabled:
        beat_schedule["incident-sla-breach-scan"] = {
            "task": "src.app.tasks.incident_ops_tasks.check_incident_sla_breaches",
            "schedule": crontab(minute=f"*/{incident_sla_min}"),
            "args": (),
        }
    if trace_recovery_enabled:
        beat_schedule["trace-broker-recovery"] = {
            "task": "src.app.tasks.incident_ops_tasks.trace_broker_recovery",
            "schedule": crontab(minute=f"*/{trace_recovery_min}"),
            "args": (),
        }
    if catalog_reindex_enabled:
        beat_schedule["catalog-reindex-nightly"] = {
            "task": "catalog.reindex_new_products",
            "schedule": crontab(minute=str(catalog_reindex_minute), hour=str(catalog_reindex_hour)),
            "args": (),
        }
    if vuln_scan_sched_enabled:
        beat_schedule["scheduled-vuln-scan-daily"] = {
            "task": "src.app.tasks.incident_ops_tasks.scheduled_vuln_scan_daily",
            "schedule": crontab(minute=str(vuln_scan_sched_minute), hour=str(vuln_scan_sched_hour)),
            "args": (),
        }
    if anomaly_snapshot_enabled:
        beat_schedule["anomaly-hourly-snapshot"] = {
            "task": "src.app.tasks.anomaly_tasks.anomaly_hourly_snapshot",
            "schedule": crontab(minute=f"*/{anomaly_snapshot_min}"),
            "args": (),
        }
    # IT-DET-03 — Config file integrity monitoring (default: every 5 min)
    if config_integrity_enabled:
        beat_schedule["config-integrity-check"] = {
            "task": "src.app.tasks.security_poll_tasks.check_config_integrity",
            "schedule": crontab(minute=f"*/{config_integrity_min}"),
            "args": (),
        }
    # IT-DET-05 — Prompt hash verification (default: every 5 min)
    if prompt_verify_enabled:
        beat_schedule["prompt-hash-verify"] = {
            "task": "src.app.tasks.security_poll_tasks.verify_prompt_hashes",
            "schedule": crontab(minute=f"*/{prompt_verify_min}"),
            "args": (),
        }
    # IT-DET-03b — Audit chain integrity verification (default: every 5 min)
    if audit_chain_verify_enabled:
        beat_schedule["audit-chain-verify"] = {
            "task": "src.app.tasks.security_poll_tasks.verify_audit_chain",
            "schedule": crontab(minute=f"*/{audit_chain_verify_min}"),
            "args": (),
        }

    # Market-intelligence pipeline — real ingestion → analysis → findings on a cadence (default-OFF).
    market_pipeline_enabled = str(os.getenv("MARKET_PIPELINE_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
    market_pipeline_min = max(1, int(os.getenv("MARKET_PIPELINE_INTERVAL_SEC", "1800"))) // 60
    if market_pipeline_enabled:
        beat_schedule["market-pipeline-refresh"] = {
            "task": "src.app.tasks.market_analysis_tasks.run_market_pipeline",
            "schedule": crontab(minute=f"*/{market_pipeline_min}"),
            "args": (),
        }

    draft_retry_enabled = str(os.getenv("FULFILLMENT_DRAFT_RETRY_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
    if draft_retry_enabled:
        beat_schedule["fulfillment-draft-retry"] = {
            "task": "src.app.tasks.fulfillment_tasks.retry_supplier_drafts",
            "schedule": crontab(minute="*"),
            "args": (),
        }

    # Data-retention sweep — UNIFORM storage-limitation (idle draft carts, stale conversation, TTL-less
    # Redis session keys). Default-OFF; NEVER IP/geo gated. Windows in config/retention_policy.json.
    retention_sweep_enabled = str(os.getenv("RETENTION_SWEEP_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
    retention_sweep_min = max(5, min(1440, int(float(os.getenv("RETENTION_SWEEP_INTERVAL_MINUTES", "60") or 60))))
    # Vision-cache prewarm — the process-local sha cache goes cold on every restart; warm the demo
    # image set on a cadence. Default-OFF; interval bounded 15min..24h.
    vision_prewarm_enabled = str(os.getenv("VISION_PREWARM_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
    vision_prewarm_min = max(15, min(1440, int(float(os.getenv("VISION_PREWARM_INTERVAL_MINUTES", "60") or 60))))
    if vision_prewarm_enabled:
        beat_schedule["vision-cache-prewarm"] = {
            "task": "src.app.tasks.vision_prewarm_tasks.prewarm_vision_cache",
            "schedule": crontab(minute=f"*/{vision_prewarm_min}") if vision_prewarm_min < 60
                        else crontab(minute=0, hour=f"*/{max(1, vision_prewarm_min // 60)}"),
            "args": (),
        }

    if retention_sweep_enabled:
        if retention_sweep_min < 60:
            _retention_sched = crontab(minute=f"*/{retention_sweep_min}")
        else:
            _retention_sched = crontab(minute=0, hour=f"*/{max(1, retention_sweep_min // 60)}")
        beat_schedule["retention-sweep"] = {
            "task": "src.app.tasks.retention_tasks.run_retention_sweep",
            "schedule": _retention_sched,
            "args": (),
        }

    # Auth token expiry cleanup — prune expired session_tokens + refresh_tokens daily.
    # Without this, both tables grow unboundedly and auth query latency degrades over months.
    beat_schedule["auth-token-prune"] = {
        "task": "src.app.tasks.security_poll_tasks.prune_expired_auth_tokens",
        "schedule": crontab(minute="15", hour="3"),  # 03:15 UTC daily, low-traffic window
        "args": (),
    }

    # Email security polling — DMARC filesystem and inbox connector
    dmarc_poll_enabled = str(os.getenv("DMARC_POLL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
    dmarc_poll_min = max(1, int(os.getenv("DMARC_POLL_INTERVAL_SEC", "900"))) // 60
    if dmarc_poll_enabled:
        beat_schedule["dmarc-filesystem-poll"] = {
            "task": "src.app.tasks.email_poll_tasks.poll_dmarc_filesystem",
            "schedule": crontab(minute=f"*/{dmarc_poll_min}"),
            "args": (),
        }
    email_connector_enabled = str(os.getenv("EMAIL_CONNECTOR_POLL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
    email_connector_min = max(1, int(os.getenv("EMAIL_CONNECTOR_POLL_INTERVAL_SEC", "300"))) // 60
    if email_connector_enabled:
        beat_schedule["email-connector-poll"] = {
            "task": "src.app.tasks.email_poll_tasks.poll_email_connector",
            "schedule": crontab(minute=f"*/{email_connector_min}"),
            "args": (),
        }
    # Attribution E3 reward feed — the task self-gates, but only schedule it when enabled.
    if str(os.getenv("ATTRIBUTION_REWARD_FEED_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on"):
        beat_schedule["attribution-reward-feed"] = {
            "task": "src.app.tasks.attribution_tasks.attribution_reward_feed",
            "schedule": crontab(minute=f"*/{max(1, int(os.getenv('ATTRIBUTION_REWARD_FEED_INTERVAL_MIN', '60')))}"),
            "args": (),
        }
    # Market signal backfill (Module 1 batch wiring) — schedule only when enabled.
    if (str(os.getenv("MARKET_SIGNAL_BACKFILL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
            or str(os.getenv("MARKET_CANONICAL_FACTS_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")):
        beat_schedule["market-signal-backfill"] = {
            "task": "src.app.tasks.market_signal_tasks.market_signal_backfill",
            "schedule": crontab(minute=f"*/{max(1, int(os.getenv('MARKET_SIGNAL_BACKFILL_INTERVAL_MIN', '15')))}"),
            "args": (),
        }
    # Experiment evaluation (the autonomous rollback cadence) — schedule only when enabled.
    if str(os.getenv("EXPERIMENT_EVAL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on"):
        beat_schedule["experiment-eval"] = {
            "task": "src.app.tasks.experiment_tasks.evaluate_experiments",
            "schedule": crontab(minute=f"*/{max(1, int(os.getenv('EXPERIMENT_EVAL_INTERVAL_MIN', '30')))}"),
            "args": (),
        }
    # Market analysis (M3 detectors → persisted findings) — schedule only when enabled.
    if str(os.getenv("MARKET_ANALYSIS_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on"):
        beat_schedule["market-analysis"] = {
            "task": "src.app.tasks.market_analysis_tasks.run_market_analysis",
            "schedule": crontab(minute=f"*/{max(1, int(os.getenv('MARKET_ANALYSIS_INTERVAL_MIN', '30')))}"),
            "args": (),
        }
    # Human-feedback backfill (returns + finding corrections → learning signal) — only when enabled.
    if str(os.getenv("HUMAN_FEEDBACK_BACKFILL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on"):
        beat_schedule["human-feedback-backfill"] = {
            "task": "src.app.tasks.human_feedback_tasks.human_feedback_backfill",
            "schedule": crontab(minute=f"*/{max(1, int(os.getenv('HUMAN_FEEDBACK_BACKFILL_INTERVAL_MIN', '30')))}"),
            "args": (),
        }
    # Shadow-action generation (findings → typed proposals, LOG-ONLY) — schedule only when enabled.
    if str(os.getenv("SHADOW_ACTIONS_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on"):
        beat_schedule["shadow-actions"] = {
            "task": "src.app.tasks.shadow_action_tasks.generate_shadow_actions",
            "schedule": crontab(minute=f"*/{max(1, int(os.getenv('SHADOW_ACTIONS_INTERVAL_MIN', '30')))}"),
            "args": (),
        }
    # Experiment watchdog (fail-safe pause if eval stale + zombie revert) — schedule only when enabled.
    if str(os.getenv("EXPERIMENT_WATCHDOG_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on"):
        beat_schedule["experiment-watchdog"] = {
            "task": "src.app.tasks.experiment_ops_tasks.experiment_watchdog",
            "schedule": crontab(minute=f"*/{max(1, int(os.getenv('EXPERIMENT_WATCHDOG_INTERVAL_MIN', '10')))}"),
            "args": (),
        }

    celery.conf.update(
        timezone="UTC",
        enable_utc=True,
        task_default_queue=default_q,
        task_queues=(Queue(default_q), Queue(swarm_q), Queue("security")),
        task_routes={
            "src.app.tasks.swarm_tasks.run_swarm": {"queue": swarm_q},
            "src.app.tasks.security_poll_tasks.poll_crowdstrike": {"queue": default_q},
            "src.app.tasks.model_ops_tasks.train_recommend_cf_nightly": {"queue": default_q},
            "src.app.tasks.model_ops_tasks.snapshot_forecast_governance": {"queue": default_q},
            "src.app.tasks.model_ops_tasks.refresh_visual_search_index": {"queue": default_q},
            "src.app.tasks.model_ops_tasks.snapshot_risk_register_daily": {"queue": default_q},
            "src.app.tasks.model_ops_tasks.reindex_catalog_nightly": {"queue": default_q},
            "catalog.reindex_new_products": {"queue": default_q},
            "src.app.tasks.incident_ops_tasks.check_incident_sla_breaches": {"queue": default_q},
            "src.app.tasks.incident_ops_tasks.trace_broker_recovery": {"queue": default_q},
            "src.app.tasks.incident_ops_tasks.scheduled_vuln_scan_daily": {"queue": default_q},
            "src.app.tasks.anomaly_tasks.anomaly_hourly_snapshot": {"queue": default_q},
            "src.app.tasks.security_poll_tasks.check_config_integrity": {"queue": default_q},
            "src.app.tasks.security_poll_tasks.verify_prompt_hashes": {"queue": default_q},
            "src.app.tasks.security_poll_tasks.verify_audit_chain": {"queue": default_q},
            "src.app.tasks.security_poll_tasks.prune_expired_auth_tokens": {"queue": default_q},
            "sandbox.detonate": {"queue": "security"},
            "src.app.tasks.email_poll_tasks.poll_dmarc_filesystem": {"queue": default_q},
            "src.app.tasks.email_poll_tasks.poll_email_connector": {"queue": default_q},
            "src.app.tasks.email_enrichment_tasks.enrich_inbound_email": {"queue": default_q},
            "src.app.tasks.attribution_tasks.attribution_reward_feed": {"queue": default_q},
            "src.app.tasks.market_signal_tasks.market_signal_backfill": {"queue": default_q},
            "src.app.tasks.experiment_tasks.evaluate_experiments": {"queue": default_q},
            "src.app.tasks.market_analysis_tasks.run_market_analysis": {"queue": default_q},
            "src.app.tasks.human_feedback_tasks.human_feedback_backfill": {"queue": default_q},
            "src.app.tasks.shadow_action_tasks.generate_shadow_actions": {"queue": default_q},
            "src.app.tasks.experiment_ops_tasks.experiment_watchdog": {"queue": default_q},
            "src.app.tasks.fulfillment_tasks.retry_supplier_drafts": {"queue": default_q},
        },
        imports=(
            "src.app.tasks.swarm_tasks",
            "src.app.tasks.security_poll_tasks",
            "src.app.tasks.model_ops_tasks",
            "src.app.tasks.incident_ops_tasks",
            "src.app.tasks.anomaly_tasks",
            "src.app.tasks.sandbox_tasks",
            "src.app.tasks.email_poll_tasks",
            "src.app.tasks.email_enrichment_tasks",
            "src.app.tasks.attribution_tasks",
            "src.app.tasks.market_signal_tasks",
            "src.app.tasks.experiment_tasks",
            "src.app.tasks.market_analysis_tasks",
            "src.app.tasks.human_feedback_tasks",
            "src.app.tasks.shadow_action_tasks",
            "src.app.tasks.experiment_ops_tasks",
            "src.app.tasks.retention_tasks",
            "src.app.tasks.vision_prewarm_tasks",
            "src.app.tasks.fulfillment_tasks",
        ),
        beat_schedule=beat_schedule,
        task_create_missing_queues=False,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        # If a worker process is killed mid-task (OOM, SIGKILL), reject the message
        # back to the broker so it gets requeued rather than silently lost.
        task_reject_on_worker_lost=True,
        # Global time limits: soft limit sends SIGTERM to the task (allowing cleanup);
        # hard limit sends SIGKILL after an extra 60s. Both configurable via env.
        task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIMEOUT_SEC", "300")),
        task_time_limit=int(os.getenv("CELERY_TASK_HARD_TIMEOUT_SEC", "360")),
    )
    return celery


celery_app = make_celery()
