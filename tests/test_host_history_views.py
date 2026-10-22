"""Unasked host history carries addresses; retirement belongs to an applied fold."""
import pytest

from ouroboros import context_compaction as cc
from ouroboros.context_budget import bound_host_row
from ouroboros.context_source_view import retire_host_rows_after_fold
from ouroboros.loop_messages import CONTEXT_FACTS_NAME
from ouroboros.main_context_authority import project_helper_predecessor_authority


def test_host_retirement_requires_applied_fold_and_keeps_unlabelled_or_changed_rows():
    old, new = (bound_host_row(CONTEXT_FACTS_NAME, text) for text in ("old", "new"))
    unlabelled = {"role": "user", "content": "old"}
    changed = {**old, "content": "owner changed the text"}
    messages = [unlabelled, old, changed, new]
    for receipt in ({}, {"status": "no_op"}, {"status": "applied", "checkpoint_ref": {"path": "x"}}):
        assert retire_host_rows_after_fold(messages, receipt) == messages
    receipt = {"status": "applied", "selection_fingerprint": "fold", "checkpoint_ref": {"path": "exact"}}
    result = retire_host_rows_after_fold(messages, receipt, observed_messages=messages)
    assert result == [unlabelled, changed, new]
    assert receipt["retired_host_row_ids"] == [cc._sha256(cc._canonical_json(old))] and receipt["retired_host_rows_source"] == {"path": "exact"}
    assert messages == [unlabelled, old, changed, new]


def test_a_fold_cannot_retire_host_arrivals_its_checkpoint_did_not_observe():
    old, late, latest = (bound_host_row(CONTEXT_FACTS_NAME, text) for text in ("old", "late", "latest"))
    receipt = {"status": "applied", "selection_fingerprint": "fold", "checkpoint_ref": {"path": "exact"}}
    assert retire_host_rows_after_fold([old, late, latest], receipt, observed_messages=[old]) == [late, latest]
    assert retire_host_rows_after_fold([old, late, latest], receipt, observed_messages=[]) == [old, late, latest]


def test_predecessor_history_is_omitted_with_size_and_reader():
    authority = {"kind": "task_result_authority", "task_id": "old", "source": {"task_id": "old", "tool": "get_task_result"},
                 "status": "failed", "result": "historical body", "plan_review_state": {"history": "old review"}}
    brief = project_helper_predecessor_authority(authority)
    assert "result" not in brief and "plan_review_state" not in brief
    assert brief["source"]["task_id"] == "old"
    assert brief["omitted_fields"]["result"] > 0 and brief["omitted_fields"]["plan_review_state"] > 0
    assert project_helper_predecessor_authority({}) == {}


@pytest.mark.parametrize("legacy", [False, True])
def test_delegation_fact_contains_identity_and_reader_without_execution_bodies(monkeypatch, legacy):
    from ouroboros.context_runtime_facts import _delegation_capability_fact
    monkeypatch.setattr("ouroboros.reviewer_slot_config.reviewer_slot_last_executions", lambda: {"r": {"status": "ok", "body": "secret body"}})
    record = {"text": "huge history", "outcome": "done", "task_id": "child", "run_id": "run-1"}
    monkeypatch.setattr("ouroboros.subagents.subagent_last_delegation",
                        lambda: record if legacy else {"latest_by_subagent": {"s": record}})
    fact = _delegation_capability_fact()
    assert fact["reviewer_slots_last"][0]["slot"] == "r"
    assert fact["subagents_last_executions"][0]["task_id"] == "child"
    assert fact["subagents_last_executions"][0]["run_id"] == "run-1"
    assert len(fact["readers"]) == 2 and "huge history" not in str(fact) and "secret body" not in str(fact)
    monkeypatch.setattr("ouroboros.reviewer_slot_config.reviewer_slot_last_executions", lambda: {})
    monkeypatch.setattr("ouroboros.subagents.subagent_last_delegation", lambda: {})
    assert _delegation_capability_fact() is None
