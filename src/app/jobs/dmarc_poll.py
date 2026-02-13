from __future__ import annotations

import os
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from src.app.security.email_security import process_dmarc_report


async def _dmarc_poll_loop(app: FastAPI, interval_sec: int, dmarc_dir: Path, tenant_id: Optional[str]):
    seen: set[str] = set()
    while True:
        try:
            for p in dmarc_dir.glob("*.xml"):
                if p.name in seen:
                    continue
                data = p.read_bytes()
                process_dmarc_report(data, tenant_id=tenant_id)
                seen.add(p.name)
            for p in dmarc_dir.glob("*.zip"):
                if p.name in seen:
                    continue
                data = p.read_bytes()
                process_dmarc_report(data, tenant_id=tenant_id)
                seen.add(p.name)
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            break
        except Exception:
            try:
                await asyncio.sleep(interval_sec)
            except Exception:
                break


def start_dmarc_poll(app: FastAPI):
    try:
        enabled = os.getenv("DMARC_POLL_ENABLED", "0").lower() in ("1", "true", "yes")
        if not enabled:
            return None
        interval = int(os.getenv("DMARC_POLL_INTERVAL_SEC", "900") or 900)
        dir_path = Path(os.getenv("DMARC_POLL_DIR", "tmp/dmarc") or "tmp/dmarc")
        tenant_id = os.getenv("DMARC_POLL_TENANT_ID")
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
            except Exception:
                return None
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except Exception:
            loop = None
        if loop:
            task = loop.create_task(_dmarc_poll_loop(app, interval, dir_path, tenant_id))
            app.state.dmarc_poll_task = task
            return task
        return None
    except Exception:
        return None


def stop_dmarc_poll(app: FastAPI):
    try:
        t = getattr(app.state, "dmarc_poll_task", None)
        if t and not t.done():
            t.cancel()
    except Exception:
        pass
