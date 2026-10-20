import json
from types import SimpleNamespace

from ouroboros.tools.recent_tasks import _handle_recent_tasks
from tests._store_shared import seed_result, unreadable_result


def _ctx(tmp_path):
    return SimpleNamespace(drive_root=tmp_path)


def _write_task(root, name, *, result="done", ts="2026-01-01T00:00:00Z", **extra):
    data = {
        "task_id": name,
        "ts": ts,
        "updated_at": ts,
        "status": "completed",
        "description": f"task {name}",
        "cost_usd": 1.25,
        "total_rounds": 3,
        "result": result,
        **extra,
    }
    seed_result(root, name, data)


def test_recent_tasks_empty_drive(tmp_path):
    data = json.loads(_handle_recent_tasks(_ctx(tmp_path)))
    assert data["running"] == []
    assert data["tasks"] == []
    assert data["unreadable_tasks"] == []
    assert data["total"] == 0
    assert data["remaining"] == 0
    assert data["next"] is None


def test_recent_tasks_uses_canonical_budget_root_from_fork(tmp_path):
    canonical = tmp_path / "canonical"
    child = tmp_path / "child"
    child.mkdir()
    _write_task(canonical, "owner-task", result="canonical-result")
    ctx = SimpleNamespace(
        drive_root=child,
        budget_drive_root=str(canonical),
        task_metadata={},
    )

    data = json.loads(_handle_recent_tasks(ctx, include_results=True))

    assert data["tasks"][0]["task_id"] == "owner-task"
    assert data["tasks"][0]["result"] == "canonical-result"


def test_recent_tasks_returns_preview_by_default(tmp_path):
    _write_task(tmp_path, "abc123", result="hello world")

    data = json.loads(_handle_recent_tasks(_ctx(tmp_path)))

    assert data["tasks"][0]["task_id"] == "abc123"
    assert data["tasks"][0]["result_preview"] == "hello world"
    assert "result" not in data["tasks"][0]
    assert "trace_summary" not in data["tasks"][0]


def test_recent_tasks_include_results_and_traces(tmp_path):
    _write_task(tmp_path, "abc123", result="full result", trace_summary="trace")

    data = json.loads(_handle_recent_tasks(
        _ctx(tmp_path),
        include_results=True,
        include_traces=True,
    ))

    assert data["tasks"][0]["result"] == "full result"
    assert data["tasks"][0]["trace_summary"] == "trace"


def test_recent_tasks_sorted_by_latest_update(tmp_path):
    _write_task(tmp_path, "older", updated_at="2026-01-01T00:00:00Z")
    _write_task(tmp_path, "newer", updated_at="2026-01-02T00:00:00Z")

    data = json.loads(_handle_recent_tasks(_ctx(tmp_path)))

    assert [row["task_id"] for row in data["tasks"]] == ["newer", "older"]


def test_recent_tasks_limit_is_clamped(tmp_path):
    for idx in range(25):
        _write_task(tmp_path, f"task{idx}", updated_at=f"2026-01-01T00:00:{idx:02d}Z")

    data = json.loads(_handle_recent_tasks(_ctx(tmp_path), limit=99))

    assert len(data["tasks"]) == 20


def test_recent_tasks_reports_unreadable_row(tmp_path, monkeypatch):
    _write_task(tmp_path, "good")
    _write_task(tmp_path, "bad")
    unreadable_result(monkeypatch, "bad", root=tmp_path)

    data = json.loads(_handle_recent_tasks(_ctx(tmp_path), limit=10))

    assert [row["task_id"] for row in data["tasks"]] == ["good"]
    assert len(data["unreadable_tasks"]) == 1
    assert data["unreadable_tasks"][0]["task_id"] == "bad"
    assert "StoreError" in data["unreadable_tasks"][0]["error"]


def test_recent_tasks_reports_running_queue(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "queue_snapshot.json").write_text(json.dumps({
        "ts": "2026-01-01T00:00:00Z",
        "running": [{"id": "run1", "text": "keep going"}],
    }), encoding="utf-8")

    data = json.loads(_handle_recent_tasks(_ctx(tmp_path)))

    assert data["running"] == [{
        "task_id": "run1",
        "status": "running",
        "description": "keep going",
        "ts": "2026-01-01T00:00:00Z",
    }]


def test_recent_tasks_row_lists_facts_and_addresses_not_bodies(tmp_path):
    """A listing row is facts, previews and the full read's address: no artifact manifest, contract brief
    or tool-error entries ride in it (20.10: one 20-row page was 1,486,244 chars)."""
    _write_task(
        tmp_path, "big",
        description="Watch the community",
        artifact_bundle={"schema_version": 1, "status": "ready", "errors": [],
                         "artifacts": [{"kind": "task_artifact", "path": f"MANIFEST-{i}"} for i in range(400)]},
        task_contract={"schema_version": 1, "task_type": "task", "objective": "Watch the community",
                       "context": "BRIEF-MARK " * 5_000, "delegation_budget": {"may_delegate": True},
                       "predecessor_authority": {"result": "PREDECESSOR-MARK " * 3_000}},
        outcome_axes={"execution": {"status": "degraded",
                                    "unresolved_tool_errors": [{"result": "ERROR-MARK " * 50}] * 30}},
    )

    text = _handle_recent_tasks(_ctx(tmp_path), limit=1)
    row = json.loads(text)["tasks"][0]

    for marker in ("MANIFEST-", "PREDECESSOR-MARK", "ERROR-MARK"):
        assert marker not in text
    reader = "get_task_result(task_id='big', include_authority=True)"
    assert row["artifact_bundle"] == {"status": "ready", "recorded_artifacts": 400, "source_read": reader}
    contract = row["task_contract"]
    assert contract["task_type"] == "task" and contract["source_read"] == reader
    assert contract["objective"] == {"same_as": "description"}
    assert contract["context"].endswith("(truncated preview from 55000 chars)")
    assert contract["omitted"] == ["delegation_budget", "predecessor_authority"]
    assert row["outcome_axes"]["execution"]["status"] == "degraded"
    assert row["outcome_axes"]["execution"]["unresolved_tool_errors"] == 30
    assert len(text) < 5_000


def test_recent_tasks_small_contract_and_bundle_stay_readable(tmp_path):
    _write_task(tmp_path, "small", task_contract={"schema_version": 1, "objective": "Do work"},
                artifact_bundle={"schema_version": 1, "status": "ready_no_changes", "artifacts": [], "errors": []})

    row = json.loads(_handle_recent_tasks(_ctx(tmp_path)))["tasks"][0]

    assert row["task_contract"] == {"objective": "Do work",
                                    "source_read": "get_task_result(task_id='small', include_authority=True)"}
    assert row["artifact_bundle"]["status"] == "ready_no_changes"
    assert row["artifact_bundle"]["recorded_artifacts"] == 0 and "errors" not in row["artifact_bundle"]


def _cover(ctx, limit, **flags):
    """Page through the listing with ``next``; return every page."""
    pages = [json.loads(_handle_recent_tasks(ctx, limit=limit, **flags))]
    while pages[-1]["next"]:
        pages.append(json.loads(_handle_recent_tasks(ctx, **pages[-1]["next"])))
    return pages


def test_recent_tasks_page_holds_whole_rows_within_its_declared_size(tmp_path, monkeypatch):
    from ouroboros.tools import recent_tasks

    for idx in range(12):
        _write_task(tmp_path, f"task{idx:02d}", result="r" * 700, updated_at=f"2026-01-01T00:00:{idx:02d}Z")
    monkeypatch.setattr(recent_tasks, "tool_result_limit", lambda name: 6_000)

    pages = _cover(_ctx(tmp_path), 20)

    seen = [row["task_id"] for page in pages for row in page["tasks"]]
    assert seen == [f"task{idx:02d}" for idx in reversed(range(12))], "every row once, in order"
    assert len(pages) > 1
    for page in pages:
        assert len(recent_tasks._page_json(page)) <= 6_000
        assert page["returned"] == len(page["tasks"])
        if page["next"]:
            assert page["next"]["offset"] == page["offset"] + page["returned"]
            assert page["page_chars_bound"] == 6_000


def test_recent_tasks_page_fit_stays_quiet_when_rows_fit_and_for_explicit_bodies(tmp_path, monkeypatch):
    from ouroboros.tools import recent_tasks

    for idx in range(5):
        _write_task(tmp_path, f"task{idx}", result="r" * 700, updated_at=f"2026-01-01T00:00:{idx:02d}Z")

    whole = json.loads(_handle_recent_tasks(_ctx(tmp_path), limit=5))
    assert whole["returned"] == 5 and whole["next"] is None and "page_chars_bound" not in whole

    monkeypatch.setattr(recent_tasks, "tool_result_limit", lambda name: 1_000)
    bodies = json.loads(_handle_recent_tasks(_ctx(tmp_path), limit=5, include_results=True))
    assert bodies["returned"] == 5 and "page_chars_bound" not in bodies
    assert all(row["result"] == "r" * 700 for row in bodies["tasks"]), "asked-for bodies arrive whole"


def test_recent_tasks_oversized_single_row_becomes_an_address_and_advances(tmp_path, monkeypatch):
    from ouroboros.tools import recent_tasks

    _write_task(tmp_path, "wide", result="w" * 700, updated_at="2026-01-01T00:00:02Z")
    _write_task(tmp_path, "next", updated_at="2026-01-01T00:00:01Z")
    monkeypatch.setattr(recent_tasks, "tool_result_limit", lambda name: 900)

    page = json.loads(_handle_recent_tasks(_ctx(tmp_path), limit=2))

    assert page["returned"] == 1 and page["next"]["offset"] == 1
    stub = page["tasks"][0]
    assert stub["task_id"] == "wide" and stub["omitted_chars"] > 900
    assert stub["source_read"] == "get_task_result(task_id='wide', include_authority=True)"
    assert "result_preview" not in stub
    after = json.loads(_handle_recent_tasks(_ctx(tmp_path), **page["next"]))
    assert [row["task_id"] for row in after["tasks"]] == ["next"]


def test_recent_tasks_scoped_reader_names_the_binding_scope():
    from ouroboros.tools.recent_tasks import _source_read

    assert _source_read("t1", None) == "get_task_result(task_id='t1', include_authority=True)"
    assert _source_read("t1", "binding-1") == (
        "get_task_result(task_id='t1', include_authority=True, presence_scope='own_binding')")


def test_recent_tasks_running_rows_preview_long_queue_text(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "queue_snapshot.json").write_text(json.dumps({
        "running": [{"id": "run1", "text": "QUEUE-TEXT " * 2_000}],
    }), encoding="utf-8")

    row = json.loads(_handle_recent_tasks(_ctx(tmp_path)))["running"][0]

    assert row["description"].endswith("(truncated preview from 22000 chars)")
    assert len(row["description"]) < 300
