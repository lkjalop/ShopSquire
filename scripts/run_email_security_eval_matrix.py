from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.security.email_eval_matrix import build_evaluation_report, write_evaluation_report


def main() -> int:
    report = build_evaluation_report()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path("runs") / "test_reports" / f"email_security_eval_matrix_{stamp}.json"
    written = write_evaluation_report(report, out)
    print(written)
    print(report.get("summary") or {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
