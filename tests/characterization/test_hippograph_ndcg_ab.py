from tests.characterization.hippograph_ndcg_ab import evaluate


def test_shadow_graph_influence_stays_off_without_measured_uplift():
    report = evaluate()
    assert report["provisional"] is True
    assert report["summary"]["cases"] == 8
    assert report["summary"]["delta"] <= 0
    assert report["summary"]["decision"] == "keep_evidence_only"
