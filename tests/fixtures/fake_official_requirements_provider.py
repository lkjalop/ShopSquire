"""Local provider fixture for the governed external-research browser proof."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _claim(key: str, value: int, unit: str) -> dict[str, object]:
    return {
        "need_id": f"recommended-{key}",
        "claim_type": "recommended_requirements",
        "source_record_id": f"fixture-workstation-2026:{key}",
        "source_revision": "2026.08",
        "observed_at": "2026-08-07T00:00:00Z",
        "citation_id": f"docs.vendor.example/workstation#{key}",
        "claim": f"The recommended workstation configuration requires {key} >= {value} {unit}.",
        "confidence": 0.98,
        "attribute_key": key,
        "operator": ">=",
        "value": value,
        "unit": unit,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        body = json.dumps({
            "results": [{
                "title": "Enrolled official workstation requirements",
                "url": "https://docs.vendor.example/workstation/requirements-2026",
                "snippet": "Recommended local interactive simulation workstation requirements.",
                "claim_candidates": [
                    _claim("ram_gb", 32, "GB"),
                    _claim("gpu_vram_gb", 8, "GB"),
                ],
            }],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
