from src.app.services.promise_graph_projection import project_delivery_promise


def test_promise_graph_selects_verified_path_not_missing_capacity_path():
    view = project_delivery_promise({"paths": [
        [{"properties": {"lead_time_days_p50": 2}}],
        [{"properties": {"lead_time_days_p50": 4, "capacity_units": 30}}],
    ]}, requested_quantity=30, deadline_days=10)

    assert view.status == "feasible" and view.selected_path_index == 1
    assert view.paths[0].capacity.state == "not_disclosed"


def test_empty_and_unavailable_are_not_converted_to_zero_capacity():
    empty = project_delivery_promise(
        {"paths": []}, requested_quantity=30, deadline_days=10, source_status="healthy",
    )
    unavailable = project_delivery_promise(
        {"paths": []}, requested_quantity=30, deadline_days=10,
        source_status="unavailable",
    )

    assert empty.status == "empty"
    assert unavailable.status == "unavailable"


def test_verified_capacity_or_deadline_failure_is_explicit():
    view = project_delivery_promise({"paths": [[
        {"properties": {"lead_time_days_p50": 8, "capacity_units": 12}},
    ]]}, requested_quantity=30, deadline_days=2)

    assert view.status == "failed"
    assert set(view.paths[0].reasons) == {"deadline_failed", "quantity_failed"}
