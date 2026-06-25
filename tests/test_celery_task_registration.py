"""Guards that newly-added Celery tasks are actually WIRED into the app.

A task that exists as a function but is never imported into the Celery app is inert — setting its
enable-flag does nothing (the gap GPT-5.5 caught for market_signal; the same gap existed for the E3
reward feed). This locks the import + route wiring, and confirms the modules register their tasks.
"""
from __future__ import annotations

from src.app.workers.celery_app import celery_app

_ATTR = "src.app.tasks.attribution_tasks"
_MKT = "src.app.tasks.market_signal_tasks"


def test_task_modules_in_celery_imports():
    # The worker imports these on startup → the @celery_app.task decorators register the tasks.
    imports = set(celery_app.conf.imports or ())
    assert _ATTR in imports, "attribution_tasks must be in celery imports or the worker never loads it"
    assert _MKT in imports, "market_signal_tasks must be in celery imports or the flag is inert"


def test_new_tasks_have_routes():
    routes = celery_app.conf.task_routes or {}
    assert f"{_ATTR}.attribution_reward_feed" in routes
    assert f"{_MKT}.market_signal_backfill" in routes


def test_tasks_register_when_modules_imported():
    import src.app.tasks.attribution_tasks  # noqa: F401  (runs the @task decorator)
    import src.app.tasks.market_signal_tasks  # noqa: F401
    tasks = set(celery_app.tasks.keys())
    assert f"{_ATTR}.attribution_reward_feed" in tasks
    assert f"{_MKT}.market_signal_backfill" in tasks
