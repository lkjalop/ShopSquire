from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session


def build_trend_series(days: int = 30) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    start_date = datetime.utcnow().date() - timedelta(days=days - 1)
    start = start_date.isoformat()
    series = {"security_events": [], "incidents": [], "decision_trace_events": [], "fingerprint_alerts": []}

    with db_session() as db:
        def _counts(sql: str, key: str) -> Dict[str, int]:
            try:
                rows = db.execute(text(sql), {"start": start}).fetchall()
                return {str(r[0]): int(r[1]) for r in rows or []}
            except Exception:
                return {}

        sec = _counts(
            "SELECT DATE(event_time) as day, COUNT(*) as cnt FROM security_events "
            "WHERE DATE(event_time) >= :start GROUP BY DATE(event_time)",
            "security_events",
        )
        inc = _counts(
            "SELECT DATE(created_at) as day, COUNT(*) as cnt FROM incidents "
            "WHERE DATE(created_at) >= :start GROUP BY DATE(created_at)",
            "incidents",
        )
        dte = _counts(
            "SELECT DATE(created_at) as day, COUNT(*) as cnt FROM decision_trace_events "
            "WHERE DATE(created_at) >= :start GROUP BY DATE(created_at)",
            "decision_trace_events",
        )
        fpa = _counts(
            "SELECT DATE(created_at) as day, COUNT(*) as cnt FROM security_fingerprint_alerts "
            "WHERE DATE(created_at) >= :start GROUP BY DATE(created_at)",
            "fingerprint_alerts",
        )

    for i in range(days):
        day = (start_date + timedelta(days=i)).isoformat()
        series["security_events"].append({"day": day, "count": sec.get(day, 0)})
        series["incidents"].append({"day": day, "count": inc.get(day, 0)})
        series["decision_trace_events"].append({"day": day, "count": dte.get(day, 0)})
        series["fingerprint_alerts"].append({"day": day, "count": fpa.get(day, 0)})
    return {"days": days, "series": series}


def _ascii_chart(points: List[Dict[str, Any]], width: int = 30) -> str:
    vals = [int(p.get("count", 0) or 0) for p in points]
    if not vals:
        return "(no data)"
    max_v = max(vals) or 1
    blocks = " ▁▂▃▄▅▆▇█"
    out = []
    for v in vals[-width:]:
        idx = int(round((v / max_v) * (len(blocks) - 1)))
        out.append(blocks[idx])
    return "".join(out)


def _simple_pdf_bytes(text_content: str) -> bytes:
    lines = text_content.splitlines()
    lines = lines[:80]
    escaped = []
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        escaped.append(safe[:110])
    stream_lines = ["BT", "/F1 10 Tf", "50 780 Td", "14 TL"]
    for ln in escaped:
        stream_lines.append(f"({ln}) Tj")
        stream_lines.append("T*")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1", errors="ignore")
    objects = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objects.append(b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n")
    objects.append(b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    objects.append(f"5 0 obj << /Length {len(stream)} >> stream\n".encode("latin-1") + stream + b"\nendstream endobj\n")
    pdf = b"%PDF-1.4\n"
    xref = [0]
    for obj in objects:
        xref.append(len(pdf))
        pdf += obj
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(xref)}\n".encode("latin-1")
    pdf += b"0000000000 65535 f \n"
    for off in xref[1:]:
        pdf += f"{off:010d} 00000 n \n".encode("latin-1")
    pdf += f"trailer << /Size {len(xref)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("latin-1")
    return pdf


def export_grc_report_csv(*, days: int, risk_register: Dict[str, Any], control_rows: List[Dict[str, Any]], trend: Dict[str, Any]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "key", "value", "status", "evidence_link"])
    w.writerow(["meta", "window_days", str(days), "", ""])
    for domain in risk_register.get("domains", []):
        w.writerow(
            [
                "risk_domain",
                str(domain.get("domain")),
                str(domain.get("risk_score")),
                str(domain.get("risk_band")),
                "",
            ]
        )
    for ctrl in control_rows:
        w.writerow(["control", ctrl["control_id"], ctrl["status"], "", ctrl["evidence_link"]])
    for series_name, points in (trend.get("series") or {}).items():
        for p in points:
            w.writerow(["trend", f"{series_name}:{p.get('day')}", str(p.get("count", 0)), "", ""])
    return buf.getvalue().encode("utf-8")


def export_grc_report_markdown(*, days: int, risk_register: Dict[str, Any], control_rows: List[Dict[str, Any]], trend: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# ShopSquire GRC Report ({days} days)")
    lines.append("")
    lines.append("## Risk Register")
    for d in risk_register.get("domains", []):
        lines.append(f"- **{d.get('domain')}**: score `{d.get('risk_score')}` ({d.get('risk_band')})")
    lines.append("")
    lines.append("## Controls and Evidence Links")
    lines.append("| Control | Status | Evidence |")
    lines.append("|---|---|---|")
    for c in control_rows:
        lines.append(f"| {c['control_id']} | {c['status']} | {c['evidence_link']} |")
    lines.append("")
    lines.append("## Trend Charts")
    for name, points in (trend.get("series") or {}).items():
        lines.append(f"- `{name}`: `{_ascii_chart(points)}`")
    lines.append("")
    lines.append("## Raw Trend Data")
    lines.append("```json")
    lines.append(json.dumps(trend, indent=2))
    lines.append("```")
    return "\n".join(lines)


def export_grc_report_pdf(*, markdown_text: str) -> bytes:
    return _simple_pdf_bytes(markdown_text)
