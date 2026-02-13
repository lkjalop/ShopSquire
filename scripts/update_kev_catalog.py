import json
import urllib.request
from pathlib import Path
from datetime import datetime


KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
OUT_PATH = Path("config/security/taxonomy/kev_catalog.json")


def fetch_kev():
    with urllib.request.urlopen(KEV_URL, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def main():
    try:
        data = fetch_kev()
    except Exception as e:
        print(f"KEV download failed: {e}")
        return
    items = data.get("vulnerabilities") or []
    catalog = {}
    for v in items:
        cve = v.get("cveID")
        if not cve:
            continue
        catalog[cve.upper()] = {
            "vendor": v.get("vendorProject"),
            "product": v.get("product"),
            "name": v.get("vulnerabilityName"),
            "added_date": v.get("dateAdded"),
        }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(catalog)} KEV entries to {OUT_PATH}")


if __name__ == "__main__":
    print(f"Updating KEV catalog at {datetime.utcnow().isoformat()}Z")
    main()
