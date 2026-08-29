from __future__ import annotations

import base64

from src.app.services.image_intake import sanitize_image


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_sanitize_image_identifies_png_without_imghdr() -> None:
    result = sanitize_image(_PNG_1X1)

    assert result["status"] == "sanitized"
    assert result["mime"] == "image/png"
    assert len(result["sha256"]) == 64


def test_sanitize_image_keeps_unrecognized_bytes_explicitly_unknown() -> None:
    result = sanitize_image(b"not-an-image")

    assert result["status"] == "sanitized"
    assert result["mime"] == "unknown"
