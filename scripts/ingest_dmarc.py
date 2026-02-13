#!/usr/bin/env python
import sys
from pathlib import Path

from src.app.security.email_security import process_dmarc_report


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_dmarc.py <path-to-dmarc-xml-or-zip> [tenant_id]")
        sys.exit(1)
    path = Path(sys.argv[1])
    tenant_id = sys.argv[2] if len(sys.argv) > 2 else None
    data = path.read_bytes()
    summary = process_dmarc_report(data, tenant_id=tenant_id)
    print(f"DMARC summary: {summary}")


if __name__ == "__main__":
    main()
