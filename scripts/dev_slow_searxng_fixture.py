"""Deliberately slow, local SearXNG-shaped endpoint for disconnect certification.

This is a transport fixture, not evidence. It returns no publisher candidates and
must only be used with the dedicated local proof launcher.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class SlowSearxHandler(BaseHTTPRequestHandler):
    delay_seconds = 2.5

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if not self.path.startswith("/search"):
            self.send_error(404)
            return
        time.sleep(self.delay_seconds)
        body = json.dumps({
            "results": [],
            "answers": [],
            "unresponsive_engines": [],
        }).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18888)
    parser.add_argument("--delay-seconds", type=float, default=2.5)
    args = parser.parse_args()
    SlowSearxHandler.delay_seconds = max(0.0, args.delay_seconds)
    ThreadingHTTPServer((args.host, args.port), SlowSearxHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
