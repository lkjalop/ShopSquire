from __future__ import annotations

"""Run Redis RQ worker for ShopSquire queues.

Usage:
    python scripts/run_rq_worker.py [cv|fraud|dead-letter] [...]

Env:
    REDIS_URL=redis://localhost:6379/0
"""

import os
import sys


def main(argv: list[str]) -> int:
    try:
        from src.app.workers.rq_queue import worker_run
    except Exception as e:
        print(f"Failed to import rq_queue: {e}")
        return 1
    queues = argv[1:] if len(argv) > 1 else ["cv", "fraud", "dead-letter"]
    print(f"Starting RQ worker on queues: {queues} (REDIS_URL={os.getenv('REDIS_URL')})")
    code = worker_run(queues)
    if code == 0:
        print("Worker started successfully")
    else:
        print("Worker failed to start")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
