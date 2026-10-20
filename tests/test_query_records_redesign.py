"""Focused contract proofs for the query split and structural selectors."""
from __future__ import annotations

import hashlib
import json

from ouroboros import store, store_import
from ouroboros.tools import query_data as query
from ouroboros.tools.registry import ToolContext


def _ctx(tmp_path):
    store_import.ensure_current_store(tmp_path, with_children=False)
    store.update_task(tmp_path, "caller", lambda _old: {
        "task_id": "caller", "status": "completed", "result": "answer",
    })
    repo = tmp_path / "repo"
    repo.mkdir()
    return ToolContext(repo_dir=repo, drive_root=tmp_path, task_id="caller")


def _json(text):
    return json.loads(text)


def test_query_sql_is_same_authority_and_result_with_fewer_branch_arguments(tmp_path):
    ctx = _ctx(tmp_path)
    args = dict(db="current", query="SELECT task_id,status FROM tasks ORDER BY task_id", max_rows=5)
    legacy = _json(query._query_data(ctx, op="sql", **args))
    split = _json(query._query_sql(ctx, **args))
    assert split == legacy

    old_saved = _json(query._query_data(ctx, op="sql", save_as="old.json", **args))["saved"]
    new_saved = _json(query._query_sql(ctx, save_as="new.json", **args))["saved"]
    assert old_saved["sha256"] == new_saved["sha256"]
    assert old_saved["size"] == new_saved["size"]
    old = (tmp_path / "task_results/artifacts/caller/old.json").read_bytes()
    new = (tmp_path / "task_results/artifacts/caller/new.json").read_bytes()
    assert old == new and hashlib.sha256(new).hexdigest() == new_saved["sha256"]


def test_record_forms_preserve_legacy_results_and_validate_before_io(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    path = tmp_path / "state/review_ledger/one.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{ "value": "same bytes" }\n')
    legacy = _json(query._query_data(ctx, op="json", kind="review_ledger", ids=["one"]))
    split = _json(query._query_records(ctx, form="document", kind="review_ledger", ids=["one"]))
    assert split == legacy
    old_saved = _json(query._query_data(
        ctx, op="json", kind="review_ledger", ids=["one"], save_as="old-document.json",
    ))["saved"]
    new_saved = _json(query._query_records(
        ctx, form="document", kind="review_ledger", ids=["one"], save_as="new-document.json",
    ))["saved"]
    assert old_saved["sha256"] == new_saved["sha256"]
    artifacts = tmp_path / "task_results/artifacts/caller"
    assert (artifacts / old_saved["path"]).read_bytes() == (artifacts / new_saved["path"]).read_bytes()

    monkeypatch.setattr(query, "_query_data", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("I/O reached")))
    rejected = _json(query._query_records(
        ctx, form="document", kind="review_ledger", ids=["one"], sha256="0" * 64,
    ))
    assert rejected["status"] == "error" and rejected["code"] == "invalid_arguments"
    assert "form=document does not accept: sha256" in rejected["message"]
    wrong_kind = _json(query._query_records(ctx, form="document", kind="events_log"))
    assert wrong_kind["status"] == "error" and "not a journal kind" in wrong_kind["message"]

    from ouroboros.tools import task_trace
    monkeypatch.setattr(task_trace, "query_task_trace",
                        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("trace I/O reached")))
    wrong_operation = _json(query._query_records(
        ctx, form="task_trace", task_id="caller", operation="read_call", stream="tools",
    ))
    assert wrong_operation["status"] == "error"
    assert "operation=read_call" in wrong_operation["message"]
    wrong_stream = _json(query._query_records(
        ctx, form="task_trace", task_id="caller", operation="list", stream="private_reasoning",
    ))
    assert wrong_stream["status"] == "error" and "requires stream=" in wrong_stream["message"]
    wrong_output = _json(query._query_records(
        ctx, form="task_trace", task_id="caller", operation="list", stream="events", max_bytes=2,
    ))
    assert wrong_output["status"] == "error" and "max_bytes" in wrong_output["message"]


def test_journal_and_blob_forms_preserve_legacy_data_and_exact_export_bytes(tmp_path):
    from ouroboros.observability import write_blob

    ctx = _ctx(tmp_path)
    journal_bytes = b'{"task_id":"caller","n":1}\n {"task_id":"caller","n":2}\n'
    journal = tmp_path / "logs/events.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_bytes(journal_bytes)
    legacy_journal = _json(query._query_data(
        ctx, op="jsonl", kind="events_log", tail=0, save_as="old-journal.jsonl",
    ))
    split_journal = _json(query._query_records(
        ctx, form="journal", kind="events_log", tail=0, save_as="new-journal.jsonl",
    ))
    assert split_journal["data"] == legacy_journal["data"]
    assert split_journal["saved"]["sha256"] == legacy_journal["saved"]["sha256"]
    artifacts = tmp_path / "task_results/artifacts/caller"
    assert (artifacts / split_journal["saved"]["path"]).read_bytes() == journal_bytes

    ref = write_blob(tmp_path, {"kind": "retained", "value": [1, 2, 3]})
    legacy_blob = _json(query._query_data(
        ctx, op="blob", sha256=ref["sha256"], blob_kind="json", save_as="old-blob.json",
    ))
    split_blob = _json(query._query_records(
        ctx, form="blob", sha256=ref["sha256"], blob_kind="json", save_as="new-blob.json",
    ))
    assert split_blob["data"] == legacy_blob["data"]
    assert split_blob["saved"]["sha256"] == legacy_blob["saved"]["sha256"]
    assert ((artifacts / split_blob["saved"]["path"]).read_bytes()
            == (artifacts / legacy_blob["saved"]["path"]).read_bytes())


def test_selector_errors_disclose_structure_never_neighbor_values(tmp_path):
    ctx = _ctx(tmp_path)
    path = tmp_path / "state/queue_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "rows": [{"safe": 1, "neighbor_secret": "VALUE-MUST-NOT-LEAK"}],
    }), encoding="utf-8")

    missing = _json(query._query_records(
        ctx, form="document", kind="queue_snapshot", select="rows[0].missing",
    ))
    assert missing["status"] == "error"
    assert "path 'rows[0]'" in missing["message"] and "segment 'missing'" in missing["message"]
    assert '"neighbor_secret"' in missing["message"]
    assert "VALUE-MUST-NOT-LEAK" not in missing["message"]

    bounds = _json(query._query_records(
        ctx, form="document", kind="queue_snapshot", select="rows[4]",
    ))
    assert "array length=1" in bounds["message"]
    assert "VALUE-MUST-NOT-LEAK" not in bounds["message"]

    wrong_type = _json(query._query_records(
        ctx, form="document", kind="queue_snapshot", select="rows[0].safe.value",
    ))
    assert "expected object, got number" in wrong_type["message"]


def test_missing_filter_field_stays_a_nonmatch_through_query_records(tmp_path):
    ctx = _ctx(tmp_path)
    path = tmp_path / "logs/events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"kind":"keep","value":1}\n{"value":2}\n', encoding="utf-8")
    result = _json(query._query_records(
        ctx, form="journal", kind="events_log",
        filter={"field": "missing", "op": "eq", "value": 1}, tail=0,
    ))
    assert result["status"] == "ok" and result["data"] == []


def test_legacy_remains_advertised_first_and_new_schemas_are_closed():
    entries = query.get_tools()
    assert [entry.name for entry in entries] == ["query_data", "query_sql", "query_records"]
    assert entries[0].schema["name"] == "query_data"
    assert entries[1].schema["parameters"]["additionalProperties"] is False
    assert entries[2].schema["parameters"]["additionalProperties"] is False


def test_new_facades_are_self_describing_and_skip_the_safety_model_in_real_dispatch(tmp_path, monkeypatch):
    import ouroboros.safety as safety
    from ouroboros.tools.registry import ToolRegistry

    ctx = _ctx(tmp_path)
    entries = {entry.name: entry for entry in query.get_tools()}
    assert entries["query_sql"].safety_policy == entries["query_records"].safety_policy == "skip"
    sql_help = entries["query_sql"].schema["description"]
    records_help = entries["query_records"].schema["description"]
    assert "snapshot=true" in sql_help and "format=text" in sql_help and "SELECT task_id,status" in sql_help
    for phrase in ("document requires kind", "journal requires", "read_call requires",
                   "source_end_char", "original JSONL rows"):
        assert phrase in records_help

    monkeypatch.setattr(safety, "get_safety_mode", lambda: "full")
    monkeypatch.setattr(
        safety, "_run_llm_check",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("safety model reached")),
    )
    registry = ToolRegistry(repo_dir=ctx.repo_dir, drive_root=tmp_path)
    registry.set_context(ctx)
    sql_result = registry.execute_result("query_sql", {"query": "SELECT 1 AS value"})
    records_result = registry.execute_result("query_records", {
        "form": "document", "kind": "task_result", "ids": ["caller"],
    })
    assert sql_result.status == records_result.status == "ok"
