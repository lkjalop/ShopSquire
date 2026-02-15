"""Simple file-backed human review queue for low-confidence outputs.

This is a minimal MVP queue: new review items are written as JSON files into
`capture_dir/human_review/pending/`. Reviewed items are moved to `reviewed/`.
"""
import json
from pathlib import Path
from datetime import datetime
from . import metrics as _metrics
from typing import Dict, Any, List


class HumanReviewQueue:
    def __init__(self, capture_dir: str = "tmp/human_review"):
        self.root = Path(capture_dir)
        self.pending = self.root / "pending"
        self.reviewed = self.root / "reviewed"
        self.pending.mkdir(parents=True, exist_ok=True)
        self.reviewed.mkdir(parents=True, exist_ok=True)

    def add(self, record: Dict[str, Any]) -> str:
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
        name = f"review_{ts}.json"
        path = self.pending / name
        record["_queued_at"] = ts
        path.write_text(json.dumps(record, indent=2))
        try:
            _metrics.incr("human_review_queued")
        except Exception:
            import logging

            logging.getLogger("shopsquire.human_review").exception("Failed incrementing human_review_queued metric")
        try:
            from src.app.observability.metrics import record_human_review_queued

            record_human_review_queued()
        except Exception:
            import logging

            logging.getLogger("shopsquire.human_review").exception("Failed recording human_review_queued observability metric")
        return str(path)

    def list_pending(self) -> List[str]:
        return [str(p) for p in sorted(self.pending.glob("*.json"))]

    def pop(self) -> Dict[str, Any]:
        files = self.list_pending()
        if not files:
            return {}
        path = Path(files[0])
        data = json.loads(path.read_text())
        return {"path": str(path), "data": data}

    def mark_reviewed(self, path: str, reviewer: str, notes: str = "") -> str:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        rec = json.loads(p.read_text())
        rec["_reviewed_at"] = datetime.utcnow().isoformat()
        rec["_reviewer"] = reviewer
        rec["_notes"] = notes
        dest = self.reviewed / p.name
        dest.write_text(json.dumps(rec, indent=2))
        p.unlink()
        # record review latency if queued timestamp exists
        try:
            queued = rec.get("_queued_at")
            if queued:
                # parse queued timestamp format YYYYmmddTHHMMSSffffffZ
                queued_dt = datetime.strptime(queued, "%Y%m%dT%H%M%S%fZ")
                latency = (datetime.utcnow() - queued_dt).total_seconds()
                _metrics.incr("human_review_completed")
                _metrics.timing("human_review_latency_s", latency)
                try:
                    from src.app.observability.metrics import record_human_review_completed, record_human_review_latency

                    record_human_review_completed()
                    record_human_review_latency(latency)
                except Exception:
                    import logging

                    logging.getLogger("shopsquire.human_review").exception("Failed recording human_review completion metrics")
        except Exception:
            import logging

            logging.getLogger("shopsquire.human_review").exception("Failed handling review completion metrics and latency")
        return str(dest)
