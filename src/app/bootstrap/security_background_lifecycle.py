"""Email and supply-chain security background lifecycle registration."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI


@dataclass(frozen=True)
class BackgroundServiceRegistration:
    name: str
    module: str
    start: str
    stop: str


SECURITY_BACKGROUND_SERVICES = (
    BackgroundServiceRegistration(
        "dmarc_poll", "src.app.jobs.dmarc_poll", "start_dmarc_poll", "stop_dmarc_poll",
    ),
    BackgroundServiceRegistration(
        "grc_fingerprint", "src.app.services.grc_fingerprint",
        "start_fingerprint_worker", "stop_fingerprint_worker",
    ),
    BackgroundServiceRegistration(
        "playbook_dlq", "src.app.services.playbook_dlq_scheduler",
        "start_dlq_scheduler", "stop_dlq_scheduler",
    ),
    BackgroundServiceRegistration(
        "playbook_scheduler", "src.app.services.playbook_scheduler",
        "start_playbook_scheduler", "stop_playbook_scheduler",
    ),
    BackgroundServiceRegistration(
        "sbom", "src.app.services.sbom_scheduler", "start_sbom_scheduler", "stop_sbom_scheduler",
    ),
    BackgroundServiceRegistration(
        "threat_intel", "src.app.services.threat_intel_scheduler",
        "start_threat_intel_scheduler", "stop_threat_intel_scheduler",
    ),
    BackgroundServiceRegistration(
        "phishing_page", "src.app.services.phishing_page_worker",
        "start_phishing_page_worker", "stop_phishing_page_worker",
    ),
    BackgroundServiceRegistration(
        "url_recheck", "src.app.services.url_recheck_scheduler",
        "start_url_recheck_scheduler", "stop_url_recheck_scheduler",
    ),
    BackgroundServiceRegistration(
        "mtls_cert_monitor", "src.app.services.mtls_cert_monitor",
        "start_mtls_cert_monitor", "stop_mtls_cert_monitor",
    ),
)


def _record_runtime_failure(app: FastAPI, name: str, phase: str, exc: Exception) -> None:
    prior = list(getattr(app.state, "security_background_runtime_failures", ()))
    prior.append({"service": name, "phase": phase, "error_type": type(exc).__name__})
    app.state.security_background_runtime_failures = tuple(prior)
    logging.getLogger("shopsquire.startup").exception(
        "%s security background service %s failed: %s", phase, name, exc,
    )


def register_security_background_lifecycle(app: FastAPI) -> tuple[str, ...]:
    """Register optional services and expose import/runtime failure truth."""

    registered: list[str] = []
    import_failures: list[dict[str, str]] = []
    for registration in SECURITY_BACKGROUND_SERVICES:
        try:
            module = importlib.import_module(registration.module)
            start: Any = getattr(module, registration.start)
            stop: Any = getattr(module, registration.stop)
        except Exception as exc:
            import_failures.append({
                "service": registration.name,
                "error_type": type(exc).__name__,
            })
            logging.getLogger("shopsquire.startup").exception(
                "failed to register security background service %s: %s",
                registration.name, exc,
            )
            continue

        def start_handler(
            start_fn=start, name=registration.name,
        ):
            try:
                return start_fn(app)
            except Exception as exc:
                _record_runtime_failure(app, name, "start", exc)
                return None

        def stop_handler(
            stop_fn=stop, name=registration.name,
        ):
            try:
                return stop_fn(app)
            except Exception as exc:
                _record_runtime_failure(app, name, "stop", exc)
                return None

        app.add_event_handler("startup", start_handler)
        app.add_event_handler("shutdown", stop_handler)
        registered.append(registration.name)

    app.state.security_background_services = tuple(registered)
    app.state.security_background_import_failures = tuple(import_failures)
    app.state.security_background_runtime_failures = ()
    return tuple(registered)


__all__ = [
    "BackgroundServiceRegistration",
    "SECURITY_BACKGROUND_SERVICES",
    "register_security_background_lifecycle",
]
