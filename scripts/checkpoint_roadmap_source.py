"""Local source checkpoint plus consistent isolated SQLite backup; never publishes."""

import argparse, hashlib, json, sqlite3, subprocess, zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--database", type=Path, default=Path(".artifacts/connected-shop-2026-09-28/shop.sqlite3")
    )
    args = parser.parse_args()
    if not args.name or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for ch in args.name
    ):
        parser.error("Use a plain checkpoint name")
    root = Path(__file__).resolve().parents[1]
    db = (root / args.database).resolve()
    if not db.is_relative_to(root / ".artifacts") or not db.is_file():
        raise ValueError("existing_disposable_database_required")
    parent = root.parent / "ShopSquire-checkpoints"
    parent.mkdir(exist_ok=True)
    archive = parent / (args.name + ".zip")
    backup = parent / (args.name + ".sqlite3")
    if archive.exists() or backup.exists():
        raise ValueError("checkpoint_already_exists")
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
        )
        .decode()
        .split("\0")
    )
    allowed = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".json",
        ".jsonl",
        ".md",
        ".txt",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".yml",
        ".yaml",
        ".sql",
        ".html",
        ".css",
        ".scss",
        ".ps1",
        ".sh",
        ".bat",
        ".xml",
        ".csv",
        ".lock",
        ".bicep",
        ".sha256",
        ".template",
    }
    deny_dirs = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".artifacts",
        ".codex",
        ".codex-logs",
        "dist",
        "build",
        "__pycache__",
        "secrets",
        "credentials",
        "logs",
        "artifacts",
    }
    files = {}
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as target:
        for name in sorted(set(names)):
            path = root / name
            relative = Path(name)
            if not name or not path.is_file() or not path.resolve().is_relative_to(root):
                continue
            if any(part.lower() in deny_dirs for part in relative.parts):
                continue
            lower = relative.name.lower()
            source_code = path.suffix.lower() in {
                ".py",
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".mjs",
                ".cjs",
            }
            if lower.startswith(".env") or (
                not source_code
                and any(
                    word in lower
                    for word in (
                        "api_keys",
                        "incident_tokens",
                        "credential",
                        "secret",
                        "private_key",
                    )
                )
            ):
                continue
            fixture_image = relative.parts[0] == "tests" and path.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
            }
            if (
                path.suffix.lower() not in allowed
                and not fixture_image
                and not lower.startswith("dockerfile.")
                and lower not in {"dockerfile", "makefile", ".gitignore", ".dockerignore"}
            ):
                continue
            content = path.read_bytes()
            if len(content) > 5_000_000:
                continue
            files[name] = hashlib.sha256(content).hexdigest()
            target.writestr(name, content)
        manifest = {
            "files": files,
            "count": len(files),
            "scope": "source/config/tests/docs; excludes credentials, runtime artifacts, dependencies and large binaries",
        }
        target.writestr("SOURCE_CHECKPOINT_MANIFEST.json", json.dumps(manifest, indent=2))
    with (
        sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as source,
        sqlite3.connect(backup) as destination,
    ):
        source.backup(destination, pages=128)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        revision = destination.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    receipt = {
        "source_archive": str(archive),
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": len(files),
        "database_backup": str(backup),
        "database_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "integrity_check": integrity,
        "migration": revision,
    }
    (parent / (args.name + "-receipt.json")).write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
