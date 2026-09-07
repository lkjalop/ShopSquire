import json
from pathlib import Path

import pytest

from tests.utils import write_feature_flags


def test_writer_uses_configured_temporary_path(monkeypatch, tmp_path):
    target = tmp_path / "flags.json"
    target.write_text('{}', encoding="utf-8")
    monkeypatch.setenv("FEATURE_FLAGS_PATH", str(target))
    write_feature_flags({"isolation_sentinel": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"isolation_sentinel": True}


def test_writer_refuses_tracked_config():
    with pytest.raises(ValueError, match="tracked"):
        write_feature_flags({}, path=str(Path("config/feature_flags.json").resolve()))


def test_mutation_and_cache_are_local_to_test():
    from src.app import feature_flags
    assert "isolation_sentinel" not in feature_flags.get_flags()
    write_feature_flags({"isolation_sentinel": True})
    assert feature_flags.get_flags()["isolation_sentinel"] is True


def test_other_test_starts_without_mutation_or_cache():
    from src.app import feature_flags
    assert "isolation_sentinel" not in feature_flags.get_flags()
