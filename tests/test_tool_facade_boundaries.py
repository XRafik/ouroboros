"""New tool forms preserve dispatch authority and exact result decisions."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ouroboros.tools.registry import ToolContext, ToolRegistry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("ouroboros.safety.check_safety", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr("ouroboros.tools.github.github_cli_configured", lambda: True)
    result = ToolRegistry(repo_dir=repo, drive_root=data)
    result.set_context(ToolContext(repo_dir=repo, drive_root=data))
    return result


def test_child_decision_facade_uses_exact_existing_authority(tmp_path):
    from ouroboros.task_status import load_effective_task_result
    from ouroboros.task_tree_ledger import tree_ledger_rows
    from ouroboros.tools.join_ledger import _child_result_sha256, _decide_child_results
    from ouroboros.tools.task_tree import _tree_note
    from tests._delivery_candidate_shared import write_child

    write_child(tmp_path)
    ctx = SimpleNamespace(drive_root=tmp_path, budget_drive_root=tmp_path,
                          task_id="parent1", task_metadata={"root_task_id": "parent1"})
    digest = _child_result_sha256(load_effective_task_result(tmp_path, "child1"))
    row = {"child_task_id": "child1", "disposition": "integrated", "child_result_sha256": digest}
    assert "OK:" in _decide_child_results(ctx, [row], "Used the findings")
    before = tree_ledger_rows("parent1", data_root=tmp_path)
    assert len(before) == 1 and before[0]["payload"] == {"type": "child_result_disposition", **row}
    assert "idempotent" in _tree_note(ctx, "decision", "Used the findings",
                                    payload={"type": "child_result_disposition", **row})
    assert "INVALID" in _decide_child_results(ctx, [row], "x" * 501)
    assert "STALE" in _decide_child_results(ctx, [{**row, "child_result_sha256": "0" * 64}], "stale")
    foreign = SimpleNamespace(drive_root=tmp_path, budget_drive_root=tmp_path,
                              task_id="other", task_metadata={"root_task_id": "other"})
    assert "LINEAGE_FORBIDDEN" in _decide_child_results(foreign, [row], "foreign")
    assert tree_ledger_rows("parent1", data_root=tmp_path) == before


def test_child_decision_schema_exposes_the_actual_rationale_bound(registry):
    schema = registry.get_schema_by_name("decide_child_results")["function"]["parameters"]
    assert schema["properties"]["reason"]["maxLength"] == 500
    assert set(schema["required"]) == {"children", "reason"}
    item = schema["properties"]["children"]["items"]
    assert set(item["required"]) == {"child_task_id", "child_result_sha256", "disposition"}


@pytest.mark.parametrize("withheld,requested,args", [
    ("tree_note", "decide_child_results", {"children": [], "reason": "no"}),
    ("decide_child_results", "tree_note", {"kind": "decision", "text": "no", "payload": {"type": "child_result_disposition"}}),
    ("query_data", "query_sql", {"query": "select 1"}),
    ("query_data", "query_records", {"op": "json"}),
    ("query_sql", "query_data", {"op": "sql", "query": "select 1"}),
    ("query_records", "query_data", {"op": "json", "kind": "run"}),
    ("await_messages", "sleep_until", {"wake_after_sec": 1}),
    ("sleep_until", "await_messages", {"mode": "warm", "wake_after_sec": 1}),
    ("commit_reviewed", "vcs_commit_reviewed", {"commit_message": "no"}),
    ("vcs_commit_reviewed", "commit_reviewed", {"commit_message": "no"}),
])
def test_disabled_old_or_new_operation_cannot_be_bypassed(registry, withheld, requested, args):
    registry._ctx.task_contract = {"disabled_tools": [withheld]}
    result = registry.execute_result(requested, args)
    assert result.status == "blocked" and result.code == "RESOURCE_CONSTRAINT_BLOCKED"


def test_narrow_facade_disables_leave_unrelated_legacy_operations(registry):
    from ouroboros.tools.registry_guards import _capability_resource_guard_result

    registry._ctx.task_contract = {"disabled_tools": ["query_sql", "sleep_until", "decide_child_results"]}
    for name, args in [("query_data", {"op": "json"}), ("await_messages", {}),
                       ("tree_note", {"kind": "note", "text": "still permitted"})]:
        assert _capability_resource_guard_result(registry._ctx, name, args) is None


def test_duplicate_commit_hidden_but_still_callable_without_new_grants(registry, monkeypatch):
    from dataclasses import replace

    from ouroboros import body_candidate

    entries = registry._entries
    old, new = entries["vcs_commit_reviewed"], entries["commit_reviewed"]
    assert old.handler is new.handler
    assert old.schema["parameters"] == new.schema["parameters"]
    assert old.is_code_tool == new.is_code_tool and old.safety_policy == new.safety_policy
    assert "vcs_commit_reviewed" not in registry.available_tools()
    assert registry.get_schema_by_name("vcs_commit_reviewed") is None
    assert "commit_reviewed" in registry.available_tools()
    # Test the actual entry dispatcher, without performing a commit.
    seen = []
    entry = replace(old, handler=lambda ctx, **args: seen.append(args) or "OK: dispatched old spelling")
    monkeypatch.setattr(registry, "_entries", {**entries, old.name: entry})
    monkeypatch.setattr(body_candidate, "authoring_seam", lambda *_a, **_k: None)
    assert "dispatched old spelling" in registry.execute(old.name, {"commit_message": "fixture"})
    assert seen[0]["commit_message"] == "fixture"


@pytest.mark.parametrize("spelling", ["vcs_commit_reviewed", "commit_reviewed"])
def test_sealed_presence_keeps_exact_selected_commit_name_and_binding(registry, spelling):
    from ouroboros.presence_authority import PresenceCapabilityCeiling, PresenceToolGrant, presence_ceiling_payload
    from ouroboros.presence_capabilities import PresenceArgumentBinding
    from ouroboros.tools.registry_core import _presence_bound_args

    ceiling = PresenceCapabilityCeiling(
        skill_name="behavior", skill_content_hash="a" * 64, profile_fingerprint="b" * 64,
        state_fingerprint="c" * 64, selection_fingerprint="d" * 64, model_slot="main", inline_max_rounds=3,
        tool_grants=(PresenceToolGrant(spelling, (PresenceArgumentBinding(("scope",), "static", static_value="host-scope"),)),),
        resource_grants=(), digest="0" * 64)
    payload = presence_ceiling_payload(ceiling)
    registry._ctx.task_contract = {"capability_ceiling": payload}
    original = deepcopy(payload)
    other = "commit_reviewed" if spelling == "vcs_commit_reviewed" else "vcs_commit_reviewed"
    automatic = {"finish_task", "presence_finish", "presence_cancel_work"}
    assert set(registry.available_tools()) == {spelling} | automatic
    assert registry.get_schema_by_name(spelling) is not None
    assert registry.get_schema_by_name(other) is None
    visible = {s["function"]["name"] for s in registry.schemas(core_only=True)}
    assert spelling in visible and other not in visible
    assert visible <= {spelling} | automatic
    args, error = _presence_bound_args(registry._ctx, spelling, {"scope": "model-scope"})
    assert not error and args["scope"] == "host-scope"
    assert _presence_bound_args(registry._ctx, other, {})[1]
    assert registry._ctx.task_contract["capability_ceiling"] == original


def test_registered_short_result_reads_do_not_dispose_or_consume_children(registry):
    import json

    from ouroboros.task_status import load_effective_task_result
    from ouroboros.task_tree_ledger import tree_ledger_rows
    from tests._delivery_candidate_shared import write_child

    ctx = registry._ctx
    ctx.task_id = "parent1"
    ctx.task_metadata = {"root_task_id": "parent1", "budget_drive_root": str(ctx.drive_root)}
    write_child(ctx.drive_root)
    before = load_effective_task_result(ctx.drive_root, "child1")
    for view in ("answer", "summary", "evidence"):
        response = registry.execute_result("get_task_result", {"task_id": "child1", "view": view})
        assert response.status == "ok", response.text
        observed = json.loads(response.text)
        assert observed["view"] == view and observed["child_result_sha256"]
        assert tree_ledger_rows("parent1", data_root=ctx.drive_root) == []
        assert load_effective_task_result(ctx.drive_root, "child1") == before


def test_registered_query_forms_and_sleep_use_their_existing_consumers(registry, monkeypatch):
    import json

    from ouroboros import model_sleep
    from ouroboros.task_results import write_task_result

    ctx = registry._ctx
    ctx.task_id = "parent1"
    write_task_result(ctx.drive_root, "parent1", "completed", result="retained text")
    old = registry.execute_result("query_data", {"op": "sql", "query": "SELECT task_id FROM tasks"})
    new = registry.execute_result("query_sql", {"query": "SELECT task_id FROM tasks"})
    assert old.status == new.status == "ok"
    assert json.loads(old.text) == json.loads(new.text)
    record = registry.execute_result("query_records", {
        "form": "document", "kind": "task_result", "ids": ["parent1"], "select": "result",
    })
    assert record.status == "ok" and json.loads(record.text)["data"] == "retained text"
    seen = []
    ctx.owner_wait_callback = lambda *_a, **_k: None
    monkeypatch.setattr(model_sleep, "selectors", lambda _ctx, **chosen: chosen)
    monkeypatch.setattr(model_sleep, "request_sleep", lambda _ctx, chosen, mode:
                        seen.append((chosen, mode)) or {"reason": "ready", "mode": mode})
    sleep = registry.execute_result("sleep_until", {"tasks": ["parent1"]})
    assert sleep.status == "ok" and seen == [({"tasks": ["parent1"]}, "warm")], sleep.text
    rejected = registry.execute_result("sleep_until", {"mode": "in_slot"})
    assert rejected.status != "ok"
    assert len(seen) == 1


@pytest.mark.parametrize("spelling", ["ocr_pdf", "extract_pdf_text"])
def test_pdf_exact_alias_preserves_disabled_and_sealed_grants(registry, spelling):
    from ouroboros.presence_authority import PresenceCapabilityCeiling, PresenceToolGrant, presence_ceiling_payload
    from ouroboros.presence_capabilities import PresenceArgumentBinding
    from ouroboros.tools.registry_core import _presence_bound_args

    old, new = registry._entries["ocr_pdf"], registry._entries["extract_pdf_text"]
    assert old.handler is new.handler and old.schema["parameters"] == new.schema["parameters"]
    assert "ocr_pdf" not in registry.available_tools() and "extract_pdf_text" in registry.available_tools()
    other = "extract_pdf_text" if spelling == "ocr_pdf" else "ocr_pdf"
    registry._ctx.task_contract = {"disabled_tools": [spelling]}
    denied = registry.execute_result(other, {"path": "not-read.pdf"})
    assert denied.status == "blocked" and denied.code == "RESOURCE_CONSTRAINT_BLOCKED"
    ceiling = PresenceCapabilityCeiling(
        skill_name="pdf-reader", skill_content_hash="a" * 64, profile_fingerprint="b" * 64,
        state_fingerprint="c" * 64, selection_fingerprint="d" * 64, model_slot="main", inline_max_rounds=3,
        tool_grants=(PresenceToolGrant(spelling, (PresenceArgumentBinding(("path",), "static", static_value="one.pdf"),)),),
        resource_grants=(), digest="0" * 64)
    registry._ctx.task_contract = {"capability_ceiling": presence_ceiling_payload(ceiling)}
    original = deepcopy(registry._ctx.task_contract)
    assert registry.get_schema_by_name(spelling) is not None
    assert registry.get_schema_by_name(other) is None
    args, error = _presence_bound_args(registry._ctx, spelling, {"path": "different.pdf"})
    assert not error and args["path"] == "one.pdf"
    assert _presence_bound_args(registry._ctx, other, {})[1]
    assert registry._ctx.task_contract == original
