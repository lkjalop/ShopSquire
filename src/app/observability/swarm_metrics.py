from __future__ import annotations

from prometheus_client import Counter, Histogram

SWARM_TASKS_STARTED = Counter("sc_swarm_tasks_started_total", "Total swarm tasks started")
SWARM_TASKS_COMPLETED = Counter("sc_swarm_tasks_completed_total", "Total swarm tasks completed")
SWARM_TASK_DURATION = Histogram("sc_swarm_task_duration_seconds", "Swarm task duration seconds")
