"""Create a deterministic manifest and SHA-256 seal for a Playwright artifact directory."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import zipfile


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--git-head", required=True)
    parser.add_argument("--runtime-profile", required=True)
    parser.add_argument("--runtime-endpoint")
    args = parser.parse_args()
    root = args.artifact_dir.resolve()
    if not root.is_dir():
        raise SystemExit(f"artifact directory does not exist: {root}")
    files = [path for path in sorted(root.rglob("*")) if path.is_file()]
    if not files:
        raise SystemExit(f"artifact directory is empty: {root}")
    archive_entry = None
    if args.archive is not None:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                bundle.write(path, path.relative_to(root).as_posix())
        archive_entry = {
            "path": args.archive.name,
            "bytes": args.archive.stat().st_size,
            "sha256": _sha(args.archive),
        }
    body = {
        "schema_version": "sealed-browser-certificate-v1",
        "certificate": args.certificate,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "git_head": args.git_head,
        "runtime_profile": args.runtime_profile,
        "runtime_endpoint": args.runtime_endpoint,
        "artifact_root": root.name,
        "files": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha(path),
            }
            for path in files
        ],
        "archive": archive_entry,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()
    args.manifest.write_bytes(encoded)
    args.manifest.with_suffix(args.manifest.suffix + ".sha256").write_text(
        f"{hashlib.sha256(encoded).hexdigest()}  {args.manifest.name}\n",
        encoding="utf-8",
    )
    print(json.dumps({"files": len(files), "manifest": str(args.manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
