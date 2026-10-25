"""Own an isolated bounded PostgreSQL container for real effect-race tests."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / ".artifacts") or output.exists():
        parser.error("Use a new artifact directory")
    name = "shopsquire-roadmap-" + uuid.uuid4().hex[:12]
    image = "postgres:16-alpine"
    password = secrets.token_hex(24)

    def docker(*args):
        return subprocess.check_output(
            ["docker", *args], text=True, stderr=subprocess.STDOUT
        ).strip()

    digest = docker("image", "inspect", image, "--format", "{{.Id}}")
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--label",
                "shopsquire.owner=roadmap-test",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--publish",
                "127.0.0.1::5432",
                "--env",
                "POSTGRES_PASSWORD",
                "--env",
                "POSTGRES_DB=roadmap",
                image,
            ],
            env={**os.environ, "POSTGRES_PASSWORD": password},
            check=True,
            stdout=subprocess.DEVNULL,
        )
        port = docker("port", name, "5432/tcp").rsplit(":", 1)[1]
        for _ in range(60):
            if (
                subprocess.run(
                    ["docker", "exec", name, "pg_isready", "-U", "postgres", "-d", "roadmap"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("isolated_postgres_not_ready")
        url = "postgresql+psycopg2://postgres:" + password + "@127.0.0.1:" + port + "/roadmap"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.run_roadmap_pytests",
                "--offline",
                "--output",
                str(output),
                "tests/chaos/test_release_integrity_postgres.py",
                "tests/chaos/test_effect_sink_postgres.py",
            ],
            cwd=root,
            env={**os.environ, "TEST_POSTGRES_URL": url},
        )
        return result.returncode
    finally:
        subprocess.run(["docker", "rm", "--force", name], check=True, stdout=subprocess.DEVNULL)
        if output.exists():
            (output / "database-runtime.json").write_text(
                json.dumps(
                    dict(
                        image=image,
                        image_digest=digest,
                        database="PostgreSQL 16",
                        memory_limit="512m",
                        cpus=1,
                        external_effects="fake",
                        container_removed=True,
                    ),
                    indent=2,
                ),
                encoding="utf-8",
            )


if __name__ == "__main__":
    raise SystemExit(main())
