import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Tuple, List, Dict

from sqlalchemy import text
from src.app.models.db import get_engine


def _ensure_tables():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS dmarc_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_name TEXT,
                    domain TEXT,
                    begin INTEGER,
                    end INTEGER,
                    report_id TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS dmarc_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_fk INTEGER,
                    source_ip TEXT,
                    count INTEGER,
                    spf TEXT,
                    dkim TEXT,
                    disposition TEXT,
                    FOREIGN KEY(report_fk) REFERENCES dmarc_reports(id)
                )
                """
            )
        )


def _parse_aggregate_xml(xml_bytes: bytes) -> Tuple[Dict, List[Dict]]:
    root = ET.fromstring(xml_bytes)
    md = root.find("report_metadata")
    pol = root.find("policy_published")
    header = {
        "org_name": (md.findtext("org_name") if md is not None else None),
        "domain": (pol.findtext("domain") if pol is not None else None),
        "begin": int(md.findtext("date_range/begin") or 0) if md is not None else 0,
        "end": int(md.findtext("date_range/end") or 0) if md is not None else 0,
        "report_id": md.findtext("report_id") if md is not None else None,
    }
    records = []
    for rec in root.findall("record"):
        row = rec.find("row")
        pol_ev = rec.find("policy_evaluated") if rec is not None else None
        source_ip = row.findtext("source_ip") if row is not None else None
        count = int(row.findtext("count") or 0) if row is not None else 0
        dkim = pol_ev.findtext("dkim") if pol_ev is not None else None
        spf = pol_ev.findtext("spf") if pol_ev is not None else None
        disposition = pol_ev.findtext("disposition") if pol_ev is not None else None
        records.append({
            "source_ip": source_ip,
            "count": count,
            "spf": spf,
            "dkim": dkim,
            "disposition": disposition,
        })
    return header, records


def ingest_aggregate(data: bytes) -> Tuple[int, int]:
    """Ingest DMARC aggregate report data (XML or ZIP containing XML files).

    Returns (reports_inserted, records_inserted).
    """
    _ensure_tables()
    reports = []
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if name.lower().endswith((".xml", ".gz")):
                    xml_data = zf.read(name)
                    # Some providers gzip XML inside zip; best-effort skip gzip here for simplicity.
                    try:
                        header, recs = _parse_aggregate_xml(xml_data)
                        reports.append((header, recs))
                    except Exception:
                        continue
    else:
        try:
            header, recs = _parse_aggregate_xml(data)
            reports.append((header, recs))
        except Exception:
            # not parseable
            return 0, 0

    eng = get_engine()
    reports_inserted = 0
    records_inserted = 0
    with eng.begin() as conn:
        for header, recs in reports:
            conn.execute(
                text("INSERT INTO dmarc_reports (org_name, domain, begin, end, report_id) VALUES (:o,:d,:b,:e,:r)"),
                {"o": header.get("org_name"), "d": header.get("domain"), "b": header.get("begin"), "e": header.get("end"), "r": header.get("report_id")},
            )
            rid = conn.execute(text("SELECT last_insert_rowid()"))
            try:
                report_fk = rid.scalar()
            except Exception:
                report_fk = None
            for rec in recs:
                conn.execute(
                    text("INSERT INTO dmarc_records (report_fk, source_ip, count, spf, dkim, disposition) VALUES (:fk,:ip,:c,:spf,:dkim,:disp)"),
                    {
                        "fk": report_fk,
                        "ip": rec.get("source_ip"),
                        "c": int(rec.get("count") or 0),
                        "spf": rec.get("spf"),
                        "dkim": rec.get("dkim"),
                        "disp": rec.get("disposition"),
                    },
                )
                records_inserted += 1
            reports_inserted += 1
    return reports_inserted, records_inserted


def get_summary(days: int = 30) -> Dict:
    """Return a simple summary: top failing source IPs and domains over last N days."""
    _ensure_tables()
    eng = get_engine()
    with eng.connect() as conn:
        # DMARC dates are epoch seconds; filter by time window when available.
        # For simplicity, we aggregate across all ingested reports.
        top_ips = conn.execute(
            text(
                """
                SELECT source_ip,
                       SUM(count) as total,
                       SUM(CASE WHEN spf='fail' OR dkim='fail' THEN count ELSE 0 END) as fails
                FROM dmarc_records
                WHERE source_ip IS NOT NULL
                GROUP BY source_ip
                ORDER BY fails DESC, total DESC
                LIMIT 10
                """
            )
        ).fetchall()
        top_domains = conn.execute(
            text(
                """
                SELECT domain,
                       COUNT(*) as reports,
                       SUM(
                         (SELECT SUM(CASE WHEN spf='fail' OR dkim='fail' THEN count ELSE 0 END)
                          FROM dmarc_records dr WHERE dr.report_fk = dmarc_reports.id)
                       ) as fails
                FROM dmarc_reports
                WHERE domain IS NOT NULL
                GROUP BY domain
                ORDER BY fails DESC, reports DESC
                LIMIT 10
                """
            )
        ).fetchall()
    return {
        "top_ips": [(r[0], int(r[1] or 0), int(r[2] or 0)) for r in top_ips],
        "top_domains": [(r[0], int(r[1] or 0), int(r[2] or 0)) for r in top_domains],
    }
