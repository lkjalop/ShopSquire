"""Read Blender's platform/tier tables without flattening their columns.

These are literal observations, not a complete workload contract. In particular,
the moving requirements page does not bind an application release or establish
render performance, and numeric GPU memory does not establish API support.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import re


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.platform = ""
        self.summary = None
        self.cell = None
        self.row = []
        self.table = None
        self.tables = []

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.platform = ""
        elif tag == "summary":
            self.summary = []
        elif tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"th", "td"} and self.table is not None:
            self.cell = []

    def handle_data(self, data):
        if self.summary is not None:
            self.summary.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "summary" and self.summary is not None:
            self.platform = " ".join("".join(self.summary).split())
            self.summary = None
        elif tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.table is not None:
            self.table.append(self.row)
        elif tag == "table" and self.table is not None:
            self.tables.append((self.platform, self.table))
            self.table = None
        elif tag == "details":
            self.platform = ""


def requirement_cells(content: bytes) -> list[dict]:
    parser = _Tables()
    parser.feed(content.decode("utf-8", errors="replace"))
    cells = []
    for platform, table in parser.tables:
        if platform not in {"Windows", "macOS", "Linux"} or not table:
            continue
        headers = [cell.casefold() for cell in table[0]]
        # Fail closed on reordered/ambiguous/expanded publisher schema.
        if headers != ["", "minimum", "recommended"]:
            continue
        for row in table[1:]:
            if len(row) != 3 or row[0] not in {"OS", "CPU", "RAM", "GPU"}:
                continue
            for tier, value in zip(headers[1:], row[1:]):
                if value:
                    cells.append(dict(platform=platform, tier=tier, field=row[0], text=value))
    return cells


def blender_claims(content: bytes, *, observed_at: str, citation_url: str) -> list[dict]:
    from src.app.services.official_workload_research import _claim

    rows = []
    revision = hashlib.sha256(content).hexdigest()
    for cell in requirement_cells(content):
        field, text = cell["field"], cell["text"]
        attribute, value, unit, operator = None, None, None, ">="
        if field == "RAM" and (match := re.fullmatch(r"(\d+) GB", text)):
            attribute, value, unit = "ram_gb", int(match[1]), "GB"
        elif field == "GPU" and (match := re.match(r"^(\d+) GB VRAM\b", text)):
            attribute, value, unit = "gpu_vram_gb", int(match[1]), "GB"
        elif field == "CPU" and (match := re.match(r"^(\d+) cores\b", text)):
            attribute, value, unit = "cpu_cores", int(match[1]), "cores"
        elif field == "OS":
            attribute, value, operator = "operating_system", text, "equals"
        if attribute is None:
            continue
        section = f"{cell['platform']} / {cell['tier']} / {field}"
        row = _claim(
            "blender_official_requirements", attribute, operator, value, unit=unit,
            claim_type=f"{cell['tier']}_requirements", requirement_class=cell["tier"],
            condition=f"Platform: {cell['platform']}", statement=text,
            observed_at=observed_at, citation_url=citation_url,
        )
        # Equal values in different tiers/platforms are different obligations.
        row["claim_id"] += "-" + hashlib.sha256(section.encode()).hexdigest()[:12]
        row.update(artefact_name="Blender", artefact_version=None,
                   page_section=section, source_excerpt=text, quoted_evidence_span=text,
                   source_revision=revision, platform=cell["platform"],
                   extractor="blender_platform_table_v1")
        rows.append(row)
    return rows
