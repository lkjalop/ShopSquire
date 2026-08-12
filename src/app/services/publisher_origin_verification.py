"""Generic, non-authoritative checks for a discovered publisher origin.

These checks deliberately do not contain workload names or publisher aliases.
They establish whether the fetched document is internally consistent with the
approved HTTPS origin and buyer subject. They cannot prove corporate ownership.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, ConfigDict


_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "and", "are", "can", "could", "for", "from", "hardware", "help", "how",
    "need", "official", "only", "requirements", "software", "support", "system",
    "the", "this", "to", "use", "vendor", "what", "which", "will", "with",
}


def _terms(value: str) -> set[str]:
    return {
        token for token in _WORD.findall(str(value or "").lower())
        if len(token) > 2 and token not in _STOP
    }


def _host(value: str) -> str:
    return str(urlparse(value).hostname or "").lower().rstrip(".")


def _same_origin_family(left: str, right: str) -> bool:
    return bool(left and right and (
        left == right or left.endswith("." + right) or right.endswith("." + left)
    ))


class _OriginSignals(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_urls: list[str] = []
        self.identity_values: list[str] = []
        self._in_title = False
        self._in_json_ld = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag.lower() == "link" and "canonical" in values.get("rel", "").lower():
            if values.get("href"):
                self.canonical_urls.append(values["href"])
        if tag.lower() == "meta" and values.get("property", "").lower() in {
            "og:site_name", "og:title",
        }:
            if values.get("content"):
                self.identity_values.append(values["content"])
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "script" and "ld+json" in values.get("type", "").lower():
            self._in_json_ld = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        if tag.lower() == "script" and self._in_json_ld:
            self._in_json_ld = False
            try:
                data = json.loads("".join(self._buffer))
            except (TypeError, ValueError, json.JSONDecodeError):
                return
            self._collect_json_identity(data)

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.identity_values.append(data.strip())
        if self._in_json_ld:
            self._buffer.append(data)

    def _collect_json_identity(self, value: Any) -> None:
        if isinstance(value, list):
            for row in value[:20]:
                self._collect_json_identity(row)
        elif isinstance(value, dict):
            for key, row in value.items():
                if str(key).lower() in {"name", "publisher", "provider", "author"}:
                    if isinstance(row, str) and row.strip():
                        self.identity_values.append(row.strip())
                    elif isinstance(row, (dict, list)):
                        self._collect_json_identity(row)


class PublisherOriginVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["publisher-origin-verification-v1"] = (
        "publisher-origin-verification-v1"
    )
    status: Literal["origin_consistent", "unresolved", "contradicted"]
    ownership_authority: Literal["not_independently_verified"] = "not_independently_verified"
    approved_host: str
    canonical_hosts: list[str]
    canonical_origin_consistent: bool | None
    identity_signal_count: int
    identity_host_overlap: list[str]
    subject_overlap: list[str]
    reasons: list[str]


def verify_publisher_origin(
    *, approved_url: str, content: bytes | str, purpose: str,
) -> PublisherOriginVerification:
    approved_host = _host(approved_url)
    parser = _OriginSignals()
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    try:
        parser.feed(text[:2_000_000])
    except (ValueError, TypeError):
        pass
    canonical_hosts = sorted({
        _host(urljoin(approved_url, value)) for value in parser.canonical_urls
        if _host(urljoin(approved_url, value))
    })
    canonical_consistent = (
        None if not canonical_hosts
        else all(_same_origin_family(approved_host, host) for host in canonical_hosts)
    )
    identity_terms = _terms(" ".join(parser.identity_values))
    host_terms = _terms(approved_host.replace(".", " ").replace("-", " "))
    identity_host_overlap = sorted(identity_terms & host_terms)
    subject_overlap = sorted(_terms(text[:500_000]) & _terms(purpose))[:20]
    reasons: list[str] = []
    if canonical_consistent is False:
        reasons.append("canonical_points_to_different_origin")
        status = "contradicted"
    elif identity_host_overlap and subject_overlap:
        reasons.extend(["identity_matches_origin_host", "document_matches_buyer_subject"])
        status = "origin_consistent"
    else:
        if not identity_host_overlap:
            reasons.append("publisher_identity_not_established")
        if not subject_overlap:
            reasons.append("buyer_subject_not_found_in_document")
        status = "unresolved"
    return PublisherOriginVerification(
        status=status,
        approved_host=approved_host,
        canonical_hosts=canonical_hosts,
        canonical_origin_consistent=canonical_consistent,
        identity_signal_count=len(parser.identity_values),
        identity_host_overlap=identity_host_overlap,
        subject_overlap=subject_overlap,
        reasons=reasons,
    )


__all__ = ["PublisherOriginVerification", "verify_publisher_origin"]
