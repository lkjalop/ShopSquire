"""Run selected tests with a native exit-code receipt and UTF-8 output on Windows."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def pytest_runtime_environment(inherited, *, offline=False):
    env = {**inherited, "APP_ENV": "test", "PYTHONIOENCODING": "utf-8"}
    if offline:
        # CUDA visibility does not constrain a separate Ollama process. Block
        # every supported local alias and startup warm-up path explicitly.
        env.update(
            {
                alias: "http://127.0.0.1:1"
                for alias in ("OLLAMA_URL", "OLLAMA_BASE_URL", "OLLAMA_HOST")
            }
        )
        env.update(
            CUDA_VISIBLE_DEVICES="-1",
            VLM_WARMUP_ON_START="0",
            CV_WARMUP_ON_START="0",
            SHOPSQUIRE_ACCEPTANCE_LIVE="0",
        )
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-slow", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Disable local GPU/model aliases and startup warming; live cases require a separate run",
    )
    parser.add_argument(
        "--diagnostic-gc-interval",
        type=int,
        default=0,
        help="Measure unreachable test-object reclamation after this many teardowns; zero disables it",
    )
    parser.add_argument(
        "--separate-browser-suites",
        action="store_true",
        help="Run the Python API/service suite separately from browser/load process fixtures, as CI does",
    )
    parser.add_argument("tests", nargs="+")
    args = parser.parse_args()
    if args.diagnostic_gc_interval < 0:
        parser.error("GC interval must be non-negative")
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / ".artifacts"):
        parser.error("Output must be inside .artifacts")
    output.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        "-m",
        "pytest",
        *args.tests,
        "-q",
        "--junitxml=" + str(output / "tests.xml"),
    ]
    excluded = (
        ["tests/browser", "tests/pw", "tests/playwright", "tests/e2e", "tests/load"]
        if args.separate_browser_suites
        else []
    )
    command.extend("--ignore=" + path for path in excluded)
    if args.run_slow:
        command.append("--run-slow")
    started = datetime.now(timezone.utc).isoformat()
    clock = time.monotonic()
    with (output / "tests.log").open("w", encoding="utf-8") as log:
        env = pytest_runtime_environment(os.environ, offline=args.offline)
        env["PYTEST_RESULT_STREAM"] = str(output / "progress.jsonl")
        env["PYTEST_LAST_RUNNING_FILE"] = str(output / "last-running.txt")
        env["PYTEST_DIAGNOSTIC_GC_INTERVAL"] = str(args.diagnostic_gc_interval)
        env["PYTEST_RESOURCE_GC_STREAM"] = str(output / "gc-diagnostics.jsonl")
        result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    receipt = dict(
        started_at=started,
        elapsed_seconds=round(time.monotonic() - clock, 3),
        exit_code=result.returncode,
        tests=args.tests,
        excluded_paths=excluded,
        offline_model_isolation=args.offline,
        diagnostic_gc_interval=args.diagnostic_gc_interval,
    )
    if (output / "tests.xml").exists():
        suites = ET.parse(output / "tests.xml").getroot().findall("testsuite")
        receipt["counts"] = {
            key: sum(int(suite.get(key, "0")) for suite in suites)
            for key in ["tests", "failures", "errors", "skipped"]
        }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
