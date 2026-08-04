from __future__ import annotations

from pathlib import Path


def test_cloud_sdk_imports_are_confined_to_provider_adapters() -> None:
    app_root = Path("src/app")
    violations = []
    for path in app_root.rglob("*.py"):
        relative = path.relative_to(app_root).as_posix()
        if relative.startswith("providers/"):
            continue
        text = path.read_text(encoding="utf-8")
        if (
            "from azure" in text
            or "import azure" in text
            or "import boto3" in text
            or "from boto3" in text
            or "import botocore" in text
            or "from botocore" in text
        ):
            violations.append(relative)
    assert violations == []
