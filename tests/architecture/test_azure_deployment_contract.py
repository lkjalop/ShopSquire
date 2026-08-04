from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_azure_container_apps_define_all_runtime_roles():
    bicep = (ROOT / "infra" / "azure" / "main.bicep").read_text(encoding="utf-8")

    for resource_type in ("api", "worker", "beat", "web", "migrationJob"):
        assert f"resource {resource_type} " in bicep
    assert "AUTO_MIGRATE" in bicep
    assert "'/readyz'" in bicep
    assert "'/healthz'" in bicep
    assert "TRUSTED_PROXY_CIDRS" in bicep
    assert "local-owner-key" not in bicep
    assert "owner-api-key" in bicep


def test_web_image_packages_both_frontends_behind_same_origin():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx" / "default.conf.template").read_text(
        encoding="utf-8"
    )

    assert "frontend/package-lock.json" in dockerfile
    assert "admin-react/package-lock.json" in dockerfile
    assert "--base=/admin/" in dockerfile
    assert "location /api/" in nginx
    assert "location /admin/" in nginx


def test_application_image_installs_azure_and_otlp_runtime_dependencies():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "--extras azure" in dockerfile
    assert "opentelemetry-exporter-otlp" in pyproject
