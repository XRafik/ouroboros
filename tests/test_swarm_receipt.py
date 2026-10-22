"""Tree measurements never infer a critical path from overlapping ancestry."""
from types import SimpleNamespace

import pytest

from ouroboros import swarm_receipt as receipt
from ouroboros.task_results import load_task_result, write_task_result


def actor(name, start, end, **fields):
    return {"id": name, "start": start, "end": end, "terminal": end is not None, **fields}


def test_parallel_and_serial_intervals_measure_overlap_without_policy():
    parallel = receipt.fold_tree("root", [actor("a", 0, 10), actor("b", 0, 10)])
    serial = receipt.fold_tree("root", [actor("a", 0, 10), actor("b", 10, 20)])
    assert parallel["parallelism"]["mean_observed_parallelism"] == 2
    assert parallel["parallelism"]["overlap_sec"] == 10
    assert serial["parallelism"]["mean_observed_parallelism"] == 1
    assert serial["parallelism"]["overlap_sec"] == 0
    assert parallel["longest_causal_path"]["seconds"] is None
    assert serial["longest_causal_path"]["seconds"] is None  # serialization is not a causal edge


def test_explicit_nonoverlapping_edges_and_missing_or_ancestry_edges():
    actors = [actor("a", 0, 5), actor("b", 5, 12)]
    observed = [{"from": "a", "to": "b", "observed": True}]
    complete = {"tree": "complete", "causal_edges": "complete"}
    assert receipt.fold_tree("root", actors, edges=observed, coverage=complete)["longest_causal_path"]["seconds"] == 12
    assert receipt.fold_tree("root", actors, edges=observed)["longest_causal_path"]["seconds"] is None
    nested = [actor("a", 0, 12), actor("b", 3, 9, parent_task_id="a")]
    path = receipt.fold_tree("root", nested, edges=observed, coverage=complete)["longest_causal_path"]
    assert path["seconds"] is None and path["observed_seconds"] == 12
    assert len(path["rejected_edges"]) == 1


def test_live_child_root_end_and_unknown_interval_stay_provisional():
    coverage = {"tree": "complete"}
    actors = [actor("root", 0, 10), actor("child", 3, None)]
    provisional = receipt.fold_tree("root", actors, coverage=coverage)
    assert provisional["state"] == "provisional"
    assert provisional["coverage"]["intervals_observed"] == 1
    actors[1] = actor("child", 3, 15)
    assert receipt.fold_tree("root", actors, coverage=coverage)["state"] == "closed"
    assert receipt.fold_tree("root", actors)["state"] == "provisional"


def test_cost_identity_account_context_and_mind_claim_are_separate():
    usage = [{"attempt_id": "api", "task_id": "root", "kind": "attempt", "cost_usd": None,
              "physical_context": {"capacity_total_tokens": 100, "target_total_tokens": 50}, "prompt_tokens": 43},
             {"attempt_id": "session", "task_id": "child", "kind": "subscription_session",
              "cost_usd": 0, "cost_final": True, "credential_profile_id": "account-a", "subscription_route": "codex"}]
    result = receipt.fold_tree("root", [], usage=usage + [usage[1]], coverage={"usage": "complete"},
                               mind_comparison="I would choose solo next time.")
    assert len(result["cost"]["attempts"]) == 2 and result["cost"]["total_usd"] is None
    assert result["cost"]["unknown_attempts"] == 1
    assert result["cost"]["attempts"][1]["account"]["credential_profile_id"] == "account-a"
    assert [p["task_id"] for p in result["supervisor_context_pressure"]] == ["root"]
    assert result["mind_comparison"]["author"] == "mind"
    usage[0].update(cost_usd=0.25, cost_final=True)
    result = receipt.fold_tree("root", [], usage=usage, coverage={"usage": "complete"})
    assert result["cost"]["total_usd"] == 0.25
    assert result["mind_comparison"]["state"] == "not_recorded"


def test_supervisor_pressure_does_not_relabel_an_executor_context():
    usage = [{"attempt_id": "api", "task_id": "child", "kind": "attempt", "physical_context": {"target_total_tokens": 50}}]
    child = actor("task:child", 0, 10, task_id="child")
    assert receipt.fold_tree("root", [child], usage=usage)["supervisor_context_pressure"] == []
    child["supervisor_route"] = {"model": "explicit-supervisor"}
    assert receipt.fold_tree("root", [child], usage=usage)["supervisor_context_pressure"][0]["task_id"] == "child"


def test_terminal_child_publication_revises_receipt_and_replay_does_not(tmp_path):
    write_task_result(tmp_path, "root", "running", started_at="2026-10-22T00:00:00Z")
    write_task_result(tmp_path, "child", "running", root_task_id="root", parent_task_id="root",
                      started_at="2026-10-22T00:01:00Z")
    receipt.publish(tmp_path, "root")
    write_task_result(tmp_path, "root", "completed", _terminal_observed=True)
    first = load_task_result(tmp_path, "root")["swarm_receipt"]
    assert first["state"] == "provisional"
    write_task_result(tmp_path, "child", "completed", _terminal_observed=True)
    closed = load_task_result(tmp_path, "root")["swarm_receipt"]
    assert closed["state"] == "closed" and closed["revision"] > first["revision"]
    write_task_result(tmp_path, "child", "completed")
    assert load_task_result(tmp_path, "root")["swarm_receipt"] == closed


def test_late_ledger_publication_revises_existing_receipt_after_transaction(tmp_path):
    from ouroboros.usage_accounting import record_subscription_session

    write_task_result(tmp_path, "root", "completed")
    receipt.publish(tmp_path, "root")
    before = load_task_result(tmp_path, "root")["swarm_receipt"]
    args = {"drive_root": tmp_path, "route": "codex", "task_id": "root", "root_task_id": "root",
            "credential_profile_id": "paid-profile", "spend_usd": 1.25}
    attempt_id = record_subscription_session("run-one", **args)
    after = load_task_result(tmp_path, "root")["swarm_receipt"]
    assert after["revision"] > before["revision"]
    assert after["cost"]["total_usd"] == 1.25
    assert after["cost"]["attempts"][0]["attempt_id"] == attempt_id
    record_subscription_session("run-one", **args)
    assert load_task_result(tmp_path, "root")["swarm_receipt"] == after


def test_late_settlement_replaces_unknown_cost_of_same_attempt(tmp_path):
    from ouroboros.usage_store import hold

    write_task_result(tmp_path, "root", "completed")
    receipt.publish(tmp_path, "root")
    previous = None
    for state in ("reserved", "dispatched", "unresolved", "settled"):
        fields = {"attempt_id": "late-api", "kind": "attempt", "state": state,
                  "task_id": "root", "root_task_id": "root", "provider": "test", "model": "test/model"}
        if state == "settled":
            fields.update(cost_usd=0.4, cost_final=True, settle_reason="late_receipt")
        with hold(tmp_path) as txn:
            previous = txn.write(fields, previous)
        result = load_task_result(tmp_path, "root")["swarm_receipt"]
        assert len(result["cost"]["attempts"]) == 1
        assert result["cost"]["total_usd"] == (0.4 if state == "settled" else None)
    assert receipt.publish(tmp_path, "root") == result


def test_sleep_selection_and_actual_wake_produce_only_observed_edges(tmp_path, monkeypatch):
    from ouroboros import model_sleep, swarm_receipt_sources
    from ouroboros import store
    from ouroboros.subagent_metrics import set_name

    ctx = SimpleNamespace(task_id="root", drive_root=tmp_path, budget_drive_root=None,
                          _model_sleep={"sleep_id": "sleep-one", "tasks": ["child"]})
    model_sleep.begin(ctx, started_at=4)
    ctx._model_sleep = None  # owner_wait clears the request before announcing the warm resume
    monkeypatch.setattr("ouroboros.swarm_wait_facts.utc_now_iso", lambda: "1970-01-01T00:00:10Z")
    model_sleep.announce_resumed(ctx, "task:child:completed")
    with store.open_store(tmp_path, write=False) as txn:
        waits = list(txn.set_rows(set_name("swarm_waits", "root")).values())
    assert waits[0]["selection"]["tasks"] == ["child"]
    assert waits[0]["woke_by"] == "task:child:completed"
    actors = {"task:root": actor("task:root", 0, 12), "task:child": actor("task:child", 4, 10)}
    edges = swarm_receipt_sources._wait_edges(actors, waits)
    assert any(e["from"] == "task:child" for e in edges)
    assert receipt.fold_tree("root", list(actors.values()), edges=edges)["longest_causal_path"]["observed_seconds"] == 8
    waits[0]["selection"]["tasks"] = []
    actors = {"task:root": actor("task:root", 0, 12), "task:child": actor("task:child", 4, 10)}
    assert not any(e["from"] == "task:child" for e in swarm_receipt_sources._wait_edges(actors, waits))


def test_ordinary_task_writes_do_not_scan_tree_until_receipt_exists(tmp_path, monkeypatch):
    monkeypatch.setattr("ouroboros.swarm_receipt_sources.tree_inputs", lambda *a, **kw: pytest.fail("tree scan"))
    write_task_result(tmp_path, "root", "running")
    write_task_result(tmp_path, "root", "completed")


def test_only_tree_end_initializes_the_tree_receipt(tmp_path):
    from ouroboros.task_finalization import build_swarm_efficiency

    write_task_result(tmp_path, "root", "running")
    write_task_result(tmp_path, "child", "running", root_task_id="root", parent_task_id="root")
    env = SimpleNamespace(drive_root=tmp_path)
    build_swarm_efficiency(env, {"id": "child", "root_task_id": "root", "parent_task_id": "root"})
    assert "swarm_receipt" not in load_task_result(tmp_path, "child")
    assert "swarm_receipt" not in load_task_result(tmp_path, "root")
    build_swarm_efficiency(env, {"id": "root"})
    assert load_task_result(tmp_path, "root")["swarm_receipt"]["state"] == "provisional"


def test_receipt_source_failure_does_not_erase_observed_fanout(tmp_path, monkeypatch):
    from tests.test_swarm_rollup import emit, build

    write_task_result(tmp_path, "parent", "running")
    emit(tmp_path)
    monkeypatch.setattr("ouroboros.swarm_receipt_sources.tree_inputs",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("unavailable source")))
    assert build(tmp_path)["subagent_count"] == 1


def test_full_task_handoff_discloses_receipt_only_when_recorded():
    import json
    from ouroboros.tools.control_task_results import _subtask_outcome_summary

    measured = receipt.fold_tree("root", [actor("root", 0, 2)])
    assert json.loads(_subtask_outcome_summary({"swarm_receipt": measured}))["swarm_receipt"] == measured
    assert "swarm_receipt" not in json.loads(_subtask_outcome_summary({}))
