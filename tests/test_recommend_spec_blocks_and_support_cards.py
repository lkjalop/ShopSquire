from src.app.routers import recommend


def test_parse_explicit_spec_blocks_min_and_recommended():
    q = (
        "for video editing minimum specs: 16GB RAM 512GB SSD i5 "
        "recommended specs: 32GB RAM 1TB SSD RTX 4060"
    )
    out = recommend._parse_explicit_spec_blocks(q)
    assert out["has_explicit_blocks"] is True
    assert out["minimum"]["ram_gb_min"] == 16
    assert out["minimum"]["storage_gb_min"] == 512
    assert out["recommended"]["ram_gb_min"] == 32
    assert out["recommended"]["storage_gb_min"] == 1024
    assert out["recommended"]["gpu_needed"] is True


def test_parse_explicit_spec_blocks_none():
    out = recommend._parse_explicit_spec_blocks("show me laptops for school around 1200")
    assert out["has_explicit_blocks"] is False
    assert out["minimum"] == {}
    assert out["recommended"] == {}


def test_infer_account_warranty_status_empty_uid():
    out = recommend._infer_account_warranty_status("")
    assert out["status"] == "unknown"
