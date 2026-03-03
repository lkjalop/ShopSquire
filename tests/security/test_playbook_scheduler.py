from src.app.services import playbook_scheduler as sched


def test_scheduler_cycle_runs_due_playbook(monkeypatch):
    monkeypatch.setattr(
        sched,
        "list_playbooks",
        lambda include_disabled=False: [
            {"id": "PB-TEST-SCHED", "version": "1.0.0", "actions": [{"type": "notify_ops"}], "schedule": {"enabled": True, "interval_minutes": 1}}
        ],
    )
    monkeypatch.setattr(sched, "_ensure_scheduler_table", lambda: None)
    monkeypatch.setattr(sched, "_get_schedule_state", lambda playbook_id: {"next_run_at": None})
    monkeypatch.setattr(sched, "start_playbook_run", lambda **kwargs: "run-1")
    monkeypatch.setattr(sched, "append_playbook_step", lambda **kwargs: "s-1")
    monkeypatch.setattr(sched, "execute_typed_actions", lambda **kwargs: {"executed": [{"step_index": 0}], "failed": [], "skipped": []})
    monkeypatch.setattr(sched, "complete_playbook_run", lambda **kwargs: True)
    monkeypatch.setattr(sched, "_upsert_schedule_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(sched, "write_audit_and_event", lambda **kwargs: True)

    out = sched.run_scheduled_playbooks_cycle()
    assert int(out.get("checked") or 0) == 1
    assert int(out.get("triggered") or 0) == 1
    assert len(out.get("runs") or []) == 1

