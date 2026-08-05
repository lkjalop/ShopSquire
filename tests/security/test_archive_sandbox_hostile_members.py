from __future__ import annotations

import io
import stat
import zipfile

from src.app.security.archive_sandbox import inspect_archive


def _zip(entries: list[tuple[zipfile.ZipInfo | str, bytes]]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return out.getvalue()


def test_zip_path_traversal_is_rejected_without_extracting():
    result = inspect_archive(_zip([("../../outside.txt", b"inert")]), filename="quote.zip")
    assert result.allowed is False
    assert "path_traversal_attempt" in result.reasons


def test_zip_windows_path_traversal_is_rejected():
    result = inspect_archive(_zip([("..\\..\\outside.txt", b"inert")]), filename="quote.zip")
    assert result.allowed is False
    assert "path_traversal_attempt" in result.reasons


def test_zip_symlink_is_rejected():
    link = zipfile.ZipInfo("link-to-secret")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    result = inspect_archive(_zip([(link, b"../../secret")]), filename="quote.zip")
    assert result.allowed is False
    assert "symlink_member" in result.reasons


def test_unparseable_nested_archive_fails_closed():
    result = inspect_archive(_zip([("nested.zip", b"not-a-real-archive")]), filename="quote.zip")
    assert result.allowed is False
    assert "nested_archive_parse_error" in result.reasons
