import json
from pathlib import Path


ADJUDICATIONS = Path(__file__).resolve().parents[1] / "golden" / "v1_v2_adjudications.json"


def test_every_current_blocker_and_major_has_an_owned_disposition():
    payload = json.loads(ADJUDICATIONS.read_text(encoding="utf-8"))
    entries = payload["entries"]

    assert len(entries) == 19
    assert sum(e["recorded_severity"] == "BLOCKER" for e in entries.values()) == 6
    assert sum(e["recorded_severity"] == "MAJOR" for e in entries.values()) == 13
    assert all(e["disposition"] in {
        "known_wrong_v1", "accepted_v2_contract", "v2_regression",
        "delegated_dependency", "data_gap",
    } for e in entries.values())
    assert all(e.get("status") and e.get("reason") for e in entries.values())


def test_no_unresolved_v2_regression_is_hidden_as_accepted():
    entries = json.loads(ADJUDICATIONS.read_text(encoding="utf-8"))["entries"]
    regressions = [entry for entry in entries.values()
                   if entry["disposition"] == "v2_regression"]

    assert regressions
    assert all(entry["status"] == "fixed_v2" for entry in regressions)
