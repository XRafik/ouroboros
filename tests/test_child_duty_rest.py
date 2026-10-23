"""Child jobs rest on source facts, never on the elapsed GC/collection cadence."""
import os
import time

import pytest

from ouroboros import maintenance, maintenance_jobs, maintenance_retirement, plan_record, store
from ouroboros.task_results import write_task_result
from tests._cost_meter import BOUNDARY, CostMeter, HISTORY


def measured_rest(root, job):
    store.close_connections()
    with CostMeter(root) as meter:
        token = BOUNDARY.set("rest")
        try:
            assert maintenance.run_job(root, job) is None
        finally:
            BOUNDARY.reset(token)
    counts = meter.snapshot("rest")["counts"]
    assert counts.get("writes", 0) == 0
    assert all(counts.get(f"{kind}:{category}", 0) == 0
               for category in HISTORY for kind in ("open", "read_bytes"))
    return {key: counts.get(key, 0) for key in ("vm_steps", "statements", "json_loads")}


def test_retirement_rest_is_flat_and_time_alone_cannot_delete_but_new_inputs_can(tmp_path, monkeypatch):
    costs = []
    now = time.time()
    for scale in (1, 30):
        root = tmp_path / f"root{scale:02}"
        shots = root / "uploads/screenshots"
        shots.mkdir(parents=True)
        for index in range(10 * scale):
            (shots / f"shot{index:04}.png").write_bytes(b"kept")
        maintenance_retirement.record_startup(root, gaps=True)
        assert maintenance.run_job(root, "runtime_retirement")["state"] == "done"
        with monkeypatch.context() as clock:
            clock.setattr("ouroboros.retention.time.time", lambda: now + 400 * 86400)
            costs.append(measured_rest(root, "runtime_retirement"))
            assert len(list(shots.iterdir())) == 10 * scale
            (shots / "arrival.png").write_bytes(b"arrival")
            assert maintenance.run_job(root, "runtime_retirement")["state"] == "done"
            assert list(shots.iterdir()) == []  # old enough at the fact-triggered pass
    assert costs[0] == costs[1]


def test_child_requires_recorded_startup_success_and_keeps_unknown_recovery_links(tmp_path):
    write_task_result(tmp_path, "settled", "completed", ts="2000-01-01T00:00:00+00:00")
    tree = tmp_path / "task_trees/settled"
    tree.mkdir(parents=True)
    os.utime(tree, (1, 1))
    maintenance.run_job(tmp_path, "runtime_retirement")
    assert tree.exists(), "missing startup result is unknown, not success"
    maintenance_retirement.record_startup(tmp_path, gaps=True)
    maintenance.run_job(tmp_path, "runtime_retirement")
    assert tree.exists()
    maintenance_retirement.record_startup(tmp_path, gaps=False)
    maintenance.run_job(tmp_path, "runtime_retirement")
    assert not tree.exists()


def test_ended_plan_job_rests_flat_and_wakes_on_terminal_or_producer_facts(tmp_path, monkeypatch):
    from ouroboros.observability import persist_call
    costs = []
    for scale in (1, 30):
        root = tmp_path / f"root{scale:02}"
        for index in range(5 * scale):
            record = {**plan_record.empty_record(), "asks": [{"ask_id": "a1", "revision": 0, "ts": "t",
                "participants": [{"seat_id": "s1", "status": "pending", "dispatched": True}]}]}
            write_task_result(root, f"ended{index:04}", "completed", plan_record=record)
        assert maintenance.run_job(root, "ended_plan_asks")["state"] == "done"
        with monkeypatch.context() as clock:
            clock.setattr("ouroboros.utils.utc_now_iso", lambda: "2099-01-01T00:00:00+00:00")
            costs.append(measured_rest(root, "ended_plan_asks"))
        write_task_result(root, "new-ended", "completed")
        assert maintenance.run_job(root, "ended_plan_asks") is not None
        persist_call(root, task_id="ended0000", call_id="producer", call_type="plan_review_response",
                     payload={"producer_outcome": {}}, manifest={"surface": "plan_review", "producer_complete": True})
        assert maintenance.run_job(root, "ended_plan_asks") is not None
        assert maintenance.run_job(root, "ended_plan_asks") is None
    assert costs[0] == costs[1]


def test_a_racing_retirement_input_is_not_recorded_as_examined(tmp_path, monkeypatch):
    from ouroboros import delegate_state_sweep
    def arrive(root):
        write_task_result(root, "arrived", "completed")
        return {}
    monkeypatch.setattr(delegate_state_sweep, "sweep_settled_delegate_state", arrive)
    maintenance.run_job(tmp_path, "runtime_retirement")
    row = maintenance_jobs.job(tmp_path, "runtime_retirement")
    assert maintenance_retirement.due(tmp_path, row, {}, True)


def test_metrics_child_discovers_a_death_after_append_and_rests_after_catchup(tmp_path, monkeypatch):
    from ouroboros import subagent_metrics
    from ouroboros.utils import append_jsonl
    from tests.test_subagent_metrics import event
    subagent_metrics.publish(tmp_path, event("already-folded"))
    maintenance.run_job(tmp_path, "subagent_metrics")

    class ProcessExit(BaseException):
        pass

    def append(path, row):
        job = maintenance_jobs.job(tmp_path, "subagent_metrics")
        assert subagent_metrics.identity_key(row) == job["publication_owed"]
        return append_jsonl(path, row)

    with monkeypatch.context() as crash:
        crash.setattr(subagent_metrics, "append_jsonl", append)
        crash.setattr(subagent_metrics, "_publish_suffix", lambda *a: (_ for _ in ()).throw(ProcessExit()))
        with pytest.raises(ProcessExit):
            subagent_metrics.publish(tmp_path, event("saved-before-death"))
    assert maintenance.run_job(tmp_path, "subagent_metrics")["state"] == "done"
    assert subagent_metrics.read(tmp_path, "worker")["rows"][0]["dispatched"] == 2
    assert maintenance_jobs.job(tmp_path, "subagent_metrics")["publication_owed"] is None
    measured_rest(tmp_path, "subagent_metrics")


def test_completed_metrics_job_ignores_unrelated_events(tmp_path):
    from ouroboros import subagent_metrics
    from ouroboros.utils import append_jsonl
    from tests.test_subagent_metrics import event

    subagent_metrics.publish(tmp_path, event())
    maintenance.run_job(tmp_path, "subagent_metrics")
    for index in range(3):
        append_jsonl(tmp_path / "logs/events.jsonl", {"type": "unrelated_event", "index": index})
        measured_rest(tmp_path, "subagent_metrics")
