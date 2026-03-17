"""embed_steg_payload.py — Embed a known-safe test payload into a PNG via LSB steganography.

Usage:
    python scripts/embed_steg_payload.py --input tests/fixtures/clean.png \
        --output tests/fixtures/steg_c2_beacon.png \
        --payload "c2_beacon:interval=60:dst=203.0.113.99"  # RFC 5737 TEST-NET-3 only

Safety contract:
    * Payload strings MUST NOT contain real IP/domain targets.  The validator below
      rejects anything other than RFC 5737 (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24),
      RFC 2606 TLDs (.example, .test, .invalid, .localhost), or the literal string
      "SAFE_TEST_PAYLOAD".
    * Images embedded with this tool are for classifier regression testing only.
      They MUST live under tests/fixtures/ and MUST NOT be shipped in production images.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Safety guard: validate the payload string before writing anything.
# ---------------------------------------------------------------------------
_SAFE_IP_RE = re.compile(
    r"(192\.0\.2\.|198\.51\.100\.|203\.0\.113\.)\d{1,3}"
)
_SAFE_DOMAIN_RE = re.compile(
    r"\.(example|test|invalid|localhost)\b", re.IGNORECASE
)
_SAFE_LITERAL = "SAFE_TEST_PAYLOAD"


def _validate_payload(payload: str) -> None:
    """Raise ValueError if the payload contains non-test network targets."""
    # Strip known-safe tokens and check what remains.
    scrubbed = payload
    scrubbed = _SAFE_IP_RE.sub("__safe_ip__", scrubbed)
    scrubbed = _SAFE_DOMAIN_RE.sub(".__safe_tld__", scrubbed)
    scrubbed = scrubbed.replace(_SAFE_LITERAL, "__safe_literal__")

    # After scrubbing safe tokens, reject anything that looks like a routable IP/domain.
    suspicious_ip = re.search(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
        scrubbed,
    )
    suspicious_domain = re.search(
        r"\b[\w-]+\.(?:com|net|org|io|co|ru|cn|de|fr|info|biz)\b",
        scrubbed,
        re.IGNORECASE,
    )
    if suspicious_ip or suspicious_domain:
        raise ValueError(
            "Payload contains a potentially routable IP or domain. "
            "Only RFC 5737 TEST-NET addresses (192.0.2.x, 198.51.100.x, 203.0.113.x) "
            "and RFC 2606 TLDs (.example/.test/.invalid/.localhost) are permitted."
        )


# ---------------------------------------------------------------------------
# LSB encoding / decoding helpers
# ---------------------------------------------------------------------------

def _text_to_bits(text: str) -> list[int]:
    """Convert UTF-8 text to a flat list of bits (big-endian per byte)."""
    bits: list[int] = []
    for byte in text.encode("utf-8"):
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _bits_to_text(bits: list[int]) -> str:
    """Convert a flat list of bits back to UTF-8 text."""
    chars: list[int] = []
    for i in range(0, len(bits) - 7, 8):
        byte = 0
        for shift, b in zip(range(7, -1, -1), bits[i : i + 8]):
            byte |= b << shift
        if byte == 0:
            break  # null terminator
        chars.append(byte)
    return bytes(chars).decode("utf-8", errors="replace")


# Length prefix: 32 bits (big-endian unsigned int) before the payload bits.
_LENGTH_BITS = 32


def embed(src_path: Path, dst_path: Path, payload: str) -> None:
    """Embed *payload* into *src_path* and write to *dst_path* using red-channel LSB."""
    try:
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover
        sys.exit("Pillow is required: pip install Pillow")

    payload_bits = _text_to_bits(payload)
    length_bits: list[int] = []
    n = len(payload_bits)
    for shift in range(_LENGTH_BITS - 1, -1, -1):
        length_bits.append((n >> shift) & 1)
    all_bits = length_bits + payload_bits

    img = Image.open(src_path).convert("RGB")
    pixels = list(img.getdata())

    if len(all_bits) > len(pixels):
        raise ValueError(
            f"Payload too large: need {len(all_bits)} pixel samples, "
            f"image only has {len(pixels)}"
        )

    new_pixels: list[tuple[int, int, int]] = []
    for i, (r, g, b) in enumerate(pixels):
        if i < len(all_bits):
            # Embed in red channel LSB only
            r = (r & 0xFE) | all_bits[i]
        new_pixels.append((r, g, b))

    out = Image.new("RGB", img.size)
    out.putdata(new_pixels)  # type: ignore[arg-type]
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst_path, format="PNG")
    print(f"[embed_steg] Wrote {len(payload_bits)} payload bits into {dst_path}")


def extract(src_path: Path) -> str:
    """Extract and return the LSB-encoded payload from *src_path* (red channel)."""
    try:
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover
        sys.exit("Pillow is required: pip install Pillow")

    img = Image.open(src_path).convert("RGB")
    pixels = list(img.getdata())

    raw_bits = [(r & 1) for (r, _g, _b) in pixels]

    # Read 32-bit length prefix
    length = 0
    for shift, b in zip(range(_LENGTH_BITS - 1, -1, -1), raw_bits[:_LENGTH_BITS]):
        length |= b << shift

    if length <= 0 or length > (len(raw_bits) - _LENGTH_BITS):
        raise ValueError(f"Invalid embedded length prefix: {length}")

    payload_bits = raw_bits[_LENGTH_BITS : _LENGTH_BITS + length]
    return _bits_to_text(payload_bits)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Embed or extract an LSB steganographic test payload from a PNG.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    emb = sub.add_parser("embed", help="Embed a payload into an image.")
    emb.add_argument("--input", required=True, type=Path, help="Source PNG path.")
    emb.add_argument("--output", required=True, type=Path, help="Destination PNG path.")
    emb.add_argument("--payload", required=True, help="Plain-text payload string (RFC 5737/2606 only).")

    ext = sub.add_parser("extract", help="Extract an embedded payload from an image.")
    ext.add_argument("--input", required=True, type=Path, help="PNG with embedded payload.")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "embed":
        try:
            _validate_payload(args.payload)
        except ValueError as exc:
            print(f"[embed_steg] BLOCKED: {exc}", file=sys.stderr)
            return 1
        embed(args.input, args.output, args.payload)
    elif args.command == "extract":
        try:
            payload = extract(args.input)
            print(f"[embed_steg] Extracted payload: {payload}")
        except ValueError as exc:
            print(f"[embed_steg] Extract error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
