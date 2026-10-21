import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Tuple, List, Dict

from sqlalchemy import text
from src.app.models.db import get_engine

_MAX_BYTES = 10 * 1024 * 1024
_MAX_MEMBERS = 100


class _NoDTD(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError('dmarc_dtd_forbidden')


def _ensure_tables():
    from src.app.services.dmarc_schema import metadata
    metadata.create_all(get_engine())


def _parse_aggregate_xml(xml_bytes: bytes) -> Tuple[Dict, List[Dict]]:
    if len(xml_bytes) > _MAX_BYTES:
        raise ValueError('dmarc_uncompressed_limit')
    root = ET.fromstring(xml_bytes, parser=ET.XMLParser(target=_NoDTD()))
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
        pol_ev = row.find("policy_evaluated") if row is not None else None
        if pol_ev is None:
            pol_ev = rec.find("policy_evaluated")
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


def ingest_aggregate(data: bytes, *, tenant_id: str | None = None) -> Tuple[int, int]:
    """Ingest DMARC aggregate report data (XML or ZIP containing XML files).

    Returns (reports_inserted, records_inserted).
    """
    if len(data) > _MAX_BYTES:
        raise ValueError('dmarc_upload_limit')
    reports = []
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            members = zf.infolist()
            if len(members) > _MAX_MEMBERS or sum(m.file_size for m in members) > _MAX_BYTES:
                raise ValueError('dmarc_uncompressed_limit')
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

    from src.app.platform.tenant_context import current_tenant_id
    from src.app.services.dmarc_schema import reports as report_table, records as record_table
    tenant = tenant_id or current_tenant_id()
    _ensure_tables()
    reports_inserted = records_inserted = 0
    with get_engine().begin() as conn:
        for header, recs in reports:
            inserted = conn.execute(report_table.insert().values(**header, tenant_id=tenant))
            report_fk = inserted.inserted_primary_key[0]
            for rec in recs:
                if rec['count'] < 0:
                    raise ValueError('negative_dmarc_message_count')
                conn.execute(record_table.insert().values(**rec, report_fk=report_fk))
                records_inserted += 1
            reports_inserted += 1
    return reports_inserted, records_inserted


def get_summary(days: int = 30, *, tenant_id: str | None = None, now: int | None = None) -> Dict:
    from time import time
    from sqlalchemy import select, func, case, and_, or_
    from src.app.services.dmarc_schema import reports, records
    from src.app.platform.tenant_context import current_tenant_id
    if type(days) is not int or not 1 <= days <= 365:
        raise ValueError('invalid_dmarc_window')
    _ensure_tables()
    stamp = int(time()) if now is None else now
    tenant = tenant_id or current_tenant_id()
    valid = or_(records.c.spf == 'pass', records.c.dkim == 'pass',
                and_(records.c.spf == 'fail', records.c.dkim == 'fail'))
    failed = and_(records.c.spf == 'fail', records.c.dkim == 'fail')
    count = func.coalesce(records.c.count, 0)
    total = func.coalesce(func.sum(count), 0)
    evaluated = func.coalesce(func.sum(case((valid, count), else_=0)), 0)
    failures = func.coalesce(func.sum(case((failed, count), else_=0)), 0)
    source = reports.join(records, records.c.report_fk == reports.c.id)
    scope = and_(reports.c.tenant_id == tenant, reports.c.end >= stamp - days * 86400,
                 reports.c.begin <= stamp)
    with get_engine().connect() as conn:
        totals = conn.execute(select(total, evaluated, failures).select_from(source).where(scope)).one()
        def grouped(column):
            query = select(column, total.label('messages'), failures.label('fails')).select_from(source).where(
                scope, column.is_not(None)).group_by(column).order_by(failures.desc(), total.desc()).limit(10)
            return [(r[0], int(r[1]), int(r[2])) for r in conn.execute(query)]
        return {'tenant_id': tenant, 'days': days, 'total_messages': int(totals[0]),
                'evaluated_messages': int(totals[1]), 'failed_messages': int(totals[2]),
                'unknown_messages': int(totals[0] - totals[1]),
                'fail_rate': totals[2] / totals[1] if totals[1] else None,
                'top_ips': grouped(records.c.source_ip), 'top_domains': grouped(reports.c.domain)}
