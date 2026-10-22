"""Physical task-trace pagination, authority, and retained-source proofs."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from ouroboros import store, store_import
from ouroboros.headless import (
    copy_child_task_result,
    prepare_task_drive,
    prune_headless_task_drives,
    retry_child_task_refs,
)
from ouroboros.observability import persist_call
from ouroboros.task_results import STATUS_COMPLETED, write_task_result
from ouroboros.tools.query_data import _query_records
from ouroboros.tools.registry import ToolContext


def _ctx(root: Path, task_id: str = "parent", **metadata):
    repo = root / "repo"
    repo.mkdir(exist_ok=True)
    return ToolContext(repo_dir=repo, drive_root=root, task_id=task_id,
                       budget_drive_root=str(root), task_metadata={"budget_drive_root": str(root), **metadata})


def _call(ctx, **arguments):
    result = json.loads(_query_records(ctx, form="task_trace", **arguments))
    return result, result.get("data")


def _write_rows(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_physical_pages_split_start_timeout_and_late_settlement_across_rotation(tmp_path):
    task_id, invocation = "trace-task", "invocation-1"
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="done", terminal_origin="model_final")
    rows = [
        {"task_id": task_id, "type": "tool_call_started", "tool": "check", "invocation_id": invocation, "ts": "1"},
        {"task_id": task_id, "type": "tool_call_timeout", "tool": "check", "invocation_id": invocation, "ts": "2"},
        {"task_id": task_id, "type": "tool_call", "tool": "check", "invocation_id": invocation,
         "is_error": False, "status": "ok", "ts": "3"},
    ]
    live = tmp_path / "logs/tools.jsonl"
    _write_rows(live, rows)
    ctx = _ctx(tmp_path)

    first_result, first = _call(ctx, task_id=task_id, operation="list", stream="tools", limit=1)
    assert first_result["status"] == "ok"
    assert [row["observation"] for row in first["observations"]] == ["started"]
    assert first["observations"][0]["invocation_id"] == invocation
    assert first["observations"][0]["partial_group"] is True
    assert first["logical_grouping"] == "not_performed"

    archive = tmp_path / "archive/tools_20261020T100000.jsonl"
    archive.parent.mkdir()
    live.rename(archive)
    live.write_text(json.dumps({"task_id": "other", "type": "tool_call", "tool": "later"}) + "\n",
                    encoding="utf-8")

    combined_result, combined = _call(
        ctx, task_id=task_id, operation="list", stream="tools", limit=2, cursor=first["cursor"],
    )
    assert combined_result["status"] == "ok"
    assert [row["observation"] for row in combined["observations"]] == ["wait_ended", "settled"]
    assert all(row["partial_group"] is True for row in combined["observations"])

    # The same source-bound cursor can page more narrowly: a lone timeout never
    # becomes a claimed complete logical invocation, and late settlement remains.
    second_result, second = _call(
        ctx, task_id=task_id, operation="list", stream="tools", limit=1, cursor=first["cursor"],
    )
    assert second_result["status"] == "ok"
    assert [row["observation"] for row in second["observations"]] == ["wait_ended"]
    assert second["observations"][0]["partial_group"] is True
    third_result, third = _call(
        ctx, task_id=task_id, operation="list", stream="tools", limit=1, cursor=second["cursor"],
    )
    assert third_result["status"] == "ok"
    assert [row["observation"] for row in third["observations"]] == ["settled"]
    assert third["observations"][0]["invocation_id"] == invocation
    assert third["cursor"] is None and third["has_more"] is False


def test_log_cursor_integrity_rejects_position_tampering_after_append(tmp_path):
    task_id = "cursor-integrity"
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="done")
    events = tmp_path / "logs/events.jsonl"
    initial = [
        {"task_id": task_id, "type": "before-1", "ts": "1"},
        {"task_id": task_id, "type": "before-2", "ts": "2"},
    ]
    _write_rows(events, initial)
    ctx = _ctx(tmp_path)

    _first_result, first = _call(
        ctx, task_id=task_id, operation="list", stream="events", limit=1,
    )
    assert [row["event_type"] for row in first["observations"]] == ["before-1"]
    assert first["cursor"]["v"] == 3
    assert re.fullmatch(r"[0-9a-f]{64}", first["cursor"]["integrity"])
    source = next(row for row in first["cursor"]["sources"] if row["upper"])
    captured_upper = source["upper"]

    with events.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"task_id": task_id, "type": "after-capture", "ts": "3"}) + "\n")
    assert events.stat().st_size > captured_upper

    tampered = []
    changed_upper = copy.deepcopy(first["cursor"])
    next(row for row in changed_upper["sources"] if row["id"] == source["id"])["upper"] = events.stat().st_size
    tampered.append(changed_upper)
    changed_offset = copy.deepcopy(first["cursor"])
    next(row for row in changed_offset["sources"] if row["id"] == source["id"])["offset"] = 0
    tampered.append(changed_offset)
    changed_continuation = copy.deepcopy(first["cursor"])
    next(row for row in changed_continuation["sources"] if row["id"] == source["id"])["row_continuation"] = True
    tampered.append(changed_continuation)

    for cursor in tampered:
        refused, data = _call(
            ctx, task_id=task_id, operation="list", stream="events", cursor=cursor,
        )
        assert refused["status"] == "error" and refused["code"] == "invalid_arguments"
        assert data is None
        assert "cursor integrity changed" in refused["message"]

    unsigned = copy.deepcopy(first["cursor"])
    unsigned["v"] = 2
    unsigned.pop("integrity")
    refused, data = _call(
        ctx, task_id=task_id, operation="list", stream="events", cursor=unsigned,
    )
    assert refused["status"] == "error" and refused["code"] == "invalid_arguments"
    assert data is None

    _second_result, second = _call(
        ctx, task_id=task_id, operation="list", stream="events", cursor=first["cursor"],
    )
    assert [row["event_type"] for row in second["observations"]] == ["before-2"]
    assert len(second["observations"]) == 1
    assert second["coverage"]["source_bound_horizon"] is True
    assert second["cursor"] is None and second["has_more"] is False
    assert "after-capture" not in json.dumps(second)

    _fresh_result, fresh = _call(
        ctx, task_id=task_id, operation="list", stream="events",
    )
    assert [row["event_type"] for row in fresh["observations"]] == [
        "before-1", "before-2", "after-capture",
    ]
    assert len(fresh["observations"]) == 3


def test_log_cursor_integrity_is_bound_to_task_scope(tmp_path):
    for task_id in ("scope-left", "scope-right"):
        write_task_result(tmp_path, task_id, STATUS_COMPLETED, result=task_id)
    _write_rows(tmp_path / "logs/events.jsonl", [
        {"task_id": "scope-left", "type": "left-1", "ts": "1"},
        {"task_id": "scope-right", "type": "right-1", "ts": "2"},
        {"task_id": "scope-left", "type": "left-2", "ts": "3"},
        {"task_id": "scope-right", "type": "right-2", "ts": "4"},
    ])
    ctx = _ctx(tmp_path)
    _left_result, left = _call(
        ctx, task_id="scope-left", operation="list", stream="events", limit=1,
    )
    _right_result, right = _call(
        ctx, task_id="scope-right", operation="list", stream="events", limit=1,
    )
    assert [row["event_type"] for row in left["observations"]] == ["left-1"]
    assert [row["event_type"] for row in right["observations"]] == ["right-1"]

    forged = copy.deepcopy(left["cursor"])
    forged["task_id"] = "scope-right"
    forged["view"] = right["cursor"]["view"]
    refused, data = _call(
        ctx, task_id="scope-right", operation="list", stream="events", cursor=forged,
    )
    assert refused["status"] == "error" and refused["code"] == "invalid_arguments"
    assert data is None
    assert "cursor integrity changed" in refused["message"]

    _left_next_result, left_next = _call(
        ctx, task_id="scope-left", operation="list", stream="events", cursor=left["cursor"],
    )
    _right_next_result, right_next = _call(
        ctx, task_id="scope-right", operation="list", stream="events", cursor=right["cursor"],
    )
    assert [row["event_type"] for row in left_next["observations"]] == ["left-2"]
    assert [row["event_type"] for row in right_next["observations"]] == ["right-2"]
    assert left_next["cursor"] is None and right_next["cursor"] is None


def test_log_cursor_expires_with_process_key_but_source_read_identity_survives(tmp_path, monkeypatch):
    from ouroboros.tools import task_trace

    task_id = "cursor-process-lifetime"
    retained = []
    for index in range(2):
        call = persist_call(
            tmp_path, task_id=task_id, call_id=f"stable_call_{index}", call_type="tool_call",
            payload={"result": f"stable-body-{index}"},
        )
        retained.append({"manifest_ref": call["manifest_ref"]})
    write_task_result(
        tmp_path, task_id, STATUS_COMPLETED, result="done",
        trace_refs={"tool_call_refs": retained},
    )
    ctx = _ctx(tmp_path)

    _first_result, first = _call(
        ctx, task_id=task_id, operation="list", stream="tools", limit=1,
    )
    assert [row["call_id"] for row in first["published_calls"]] == ["stable_call_0"]
    assert first["cursor"] is not None
    source_read = copy.deepcopy(first["published_calls"][0]["source_read"])
    assert first["cursor_contract"] == {
        "lifetime": "current_runtime_process",
        "on_expiry": "restart_list_from_fresh_horizon",
        "restart_list": {
            "tool": "query_records",
            "arguments": {
                "form": "task_trace", "task_id": task_id, "operation": "list",
                "stream": "tools", "limit": 1,
            },
        },
    }
    restart_arguments = copy.deepcopy(first["cursor_contract"]["restart_list"]["arguments"])
    assert "cursor" not in restart_arguments

    old_integrity = first["cursor"]["integrity"]
    replacement_key = bytes(byte ^ 0xff for byte in task_trace._CURSOR_INTEGRITY_KEY)
    monkeypatch.setattr(task_trace, "_CURSOR_INTEGRITY_KEY", replacement_key)
    refused, data = _call(
        ctx, task_id=task_id, operation="list", stream="tools", limit=1,
        cursor=first["cursor"],
    )
    assert refused["status"] == "error" and refused["code"] == "invalid_arguments"
    assert data is None
    assert refused["message"] == (
        "task_trace cursor integrity changed or expired after a task_trace process restart; "
        "repeat operation=list for the same task/stream without cursor"
    )

    assert restart_arguments.pop("form") == "task_trace"
    fresh_result, fresh = _call(ctx, **restart_arguments)
    assert fresh_result["status"] == "ok"
    assert [row["call_id"] for row in fresh["published_calls"]] == ["stable_call_0"]
    assert fresh["cursor"]["integrity"] != old_integrity
    assert fresh["published_calls"][0]["source_read"] == source_read

    read_arguments = {key: value for key, value in source_read["arguments"].items() if key != "form"}
    metadata_result, metadata = _call(ctx, **read_arguments)
    assert metadata_result["status"] == "ok"
    source_result, source = _call(
        ctx, **read_arguments, source_start_char=0,
        source_end_char=metadata["source"]["complete_chars"],
    )
    assert source_result["status"] == "ok"
    assert "stable-body-0" in source["source"]["text"]
    assert source["source"]["raw_payload_used"] is False


def test_events_and_errors_withhold_neighbor_text_and_legacy_attempt_is_unknown(tmp_path):
    task_id = "trace-task"
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="done")
    event_row = {
        "task_id": task_id, "type": "llm_api_error", "error": "HIDDEN-ERROR-TEXT",
        "message": "HIDDEN-MESSAGE", "reasoning": "HIDDEN-REASONING", "status": "error", "ts": "1",
    }
    events_path = tmp_path / "logs/events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text("{malformed physical row}\n" + json.dumps(event_row) + "\n", encoding="utf-8")
    _write_rows(tmp_path / "logs/tools.jsonl", [{
        "task_id": task_id, "type": "tool_call", "tool": "legacy", "is_error": True, "ts": "2",
        "result_preview": "HIDDEN-RESULT",
    }])
    ctx = _ctx(tmp_path)
    _result, events = _call(ctx, task_id=task_id, operation="list", stream="events")
    encoded = json.dumps(events)
    assert "HIDDEN-ERROR-TEXT" not in encoded and "HIDDEN-REASONING" not in encoded
    assert events["observations"][0]["diagnostic_text_withheld"] is True
    assert events["observations"][0]["partial_group"] is True
    assert "invocation_id" in events["observations"][0]
    assert events["coverage"]["source_order"]
    assert any(gap["reason"] == "malformed_jsonl" for gap in events["coverage"]["gaps"])
    _result, tools = _call(ctx, task_id=task_id, operation="list", stream="tools")
    assert tools["observations"][0]["physical_attempt"] == "unknown_legacy"
    assert tools["observations"][0]["invocation_id"] is None


def test_oversized_jsonl_row_advances_only_through_bounded_gap_continuations(tmp_path):
    task_id = "bounded-jsonl"
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="done")
    events = tmp_path / "logs/events.jsonl"
    _write_rows(events, [
        {"task_id": "foreign", "type": "huge_neighbor", "payload": "x" * 300_000},
        {"task_id": task_id, "type": "target_after_huge_neighbor", "ts": "2"},
    ])
    ctx = _ctx(tmp_path)

    _first_result, first = _call(
        ctx, task_id=task_id, operation="list", stream="events",
    )
    assert first["observations"] == []
    assert first["coverage"]["scanned_bytes_this_page"] <= first["coverage"]["scan_byte_limit"]
    assert any(gap["reason"] == "oversized_jsonl_row" for gap in first["coverage"]["gaps"])
    assert first["cursor"] is not None
    assert any(row["row_continuation"] for row in first["cursor"]["sources"])

    tampered = copy.deepcopy(first["cursor"])
    continuation = next(row for row in tampered["sources"] if row["row_continuation"])
    continuation["row_continuation"] = False
    refused, data = _call(
        ctx, task_id=task_id, operation="list", stream="events", cursor=tampered,
    )
    assert refused["status"] == "error" and refused["code"] == "invalid_arguments"
    assert data is None

    _second_result, second = _call(
        ctx, task_id=task_id, operation="list", stream="events", cursor=first["cursor"],
    )
    assert second["coverage"]["scanned_bytes_this_page"] <= second["coverage"]["scan_byte_limit"]
    assert [row["event_type"] for row in second["observations"]] == ["target_after_huge_neighbor"]


def test_page_scan_charges_discarded_extension_suffix_and_retains_later_target(tmp_path, monkeypatch):
    from ouroboros.jsonl_tail import JsonlChainSnapshot

    task_id = "physical-page-cap"
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="done")
    _write_rows(tmp_path / "logs/events.jsonl", [
        {"task_id": "foreign", "type": f"padding-{index}", "payload": "x" * 66_000}
        for index in range(6)
    ] + [{"task_id": task_id, "type": "target_after_extension_suffix", "ts": "7"}])

    physical_reads = []
    original_read = JsonlChainSnapshot._read

    def measured_read(snapshot, start, end):
        physical_reads.append(end - start)
        return original_read(snapshot, start, end)

    monkeypatch.setattr(JsonlChainSnapshot, "_read", measured_read)
    cursor = None
    observed = []
    for _page in range(8):
        physical_reads.clear()
        _result, page = _call(
            _ctx(tmp_path), task_id=task_id, operation="list", stream="events",
            **({"cursor": cursor} if cursor is not None else {}),
        )
        assert sum(physical_reads) <= page["coverage"]["scan_byte_limit"]
        assert page["coverage"]["scanned_bytes_this_page"] == sum(physical_reads)
        observed.extend(row["event_type"] for row in page["observations"])
        cursor = page["cursor"]
        if cursor is None:
            break

    assert observed == ["target_after_extension_suffix"]
    assert cursor is None


def test_digest_addressed_source_uses_redacted_projection_after_promotion_pack_and_cleanup(tmp_path):
    from ouroboros import evidence_packs as packs

    parent = tmp_path / "data"
    parent.mkdir()
    task_id = "retained-child"
    child = prepare_task_drive(parent, task_id, "empty")
    assert child is not None
    trace = persist_call(
        child, task_id=task_id, call_id="tool_exact", call_type="tool_call",
        payload={"tool": "demo", "token": "RAW-SECRET-MUST-NOT-LEAK", "result": "published"},
        keep_raw=True,
    )
    write_task_result(child, task_id, STATUS_COMPLETED, result="published", terminal_origin="model_final",
                      trace_refs={"tool_call_refs": [{"manifest_ref": trace["manifest_ref"],
                                                       "redacted_projection_ref": trace["redacted_projection_ref"]}]})
    copied = copy_child_task_result(parent, {"id": task_id, "drive_root": str(child)})
    copied = retry_child_task_refs(parent, child, task_id)
    assert copied and copied["child_ref_promotion"]["status"] == "complete"
    manifest_ref = copied["trace_refs"]["tool_call_refs"][0]["manifest_ref"]

    members = packs.loose_members(parent, task_id)
    assert members
    pack_path, sidecar = packs.write_pack(parent, task_id, 1, members)
    packs.index_upsert(parent, pack_path, sidecar)
    for member in members:
        source = Path(member["source"])
        if source.is_file() and source.is_relative_to(parent / "observability/blobs"):
            source.unlink()
    report = prune_headless_task_drives(parent, retention_days=7, now=4_000_000_000.0, live=lambda _task: False)
    assert any(row["task_id"] == task_id for row in report["pruned"])
    assert not child.exists()

    ctx = _ctx(parent)
    listed_result, listed = _call(ctx, task_id=task_id, operation="list", stream="tools")
    assert listed_result["status"] == "ok"
    published = next(row for row in listed["published_calls"] if row["call_id"] == "tool_exact")
    assert published["manifest_sha256"] == manifest_ref["sha256"]
    meta_result, meta = _call(
        ctx, task_id=task_id, operation="read_call", call_id="tool_exact",
        manifest_sha256=manifest_ref["sha256"],
    )
    assert meta_result["status"] == "ok" and "text" not in meta["source"]
    source_result, source = _call(
        ctx, task_id=task_id, operation="read_call", call_id="tool_exact",
        manifest_sha256=manifest_ref["sha256"], source_start_char=0,
        source_end_char=meta["source"]["complete_chars"],
    )
    assert source_result["status"] == "ok"
    assert source["source"]["raw_payload_used"] is False
    assert "RAW-SECRET-MUST-NOT-LEAK" not in source["source"]["text"]
    assert "***REDACTED[" in source["source"]["text"]


def test_published_call_inventory_shares_the_page_limit_and_keeps_a_cursor(tmp_path):
    task_id = "many-published-calls"
    refs = []
    for index in range(24):
        retained = persist_call(
            tmp_path, task_id=task_id, call_id=f"call_{index:02d}", call_type="tool_call",
            payload={"result": index},
        )
        refs.append({"manifest_ref": retained["manifest_ref"]})
    write_task_result(
        tmp_path, task_id, STATUS_COMPLETED, result="done",
        trace_refs={"tool_call_refs": refs},
    )
    ctx = _ctx(tmp_path)

    _result, first = _call(ctx, task_id=task_id, operation="list", stream="tools", limit=1)
    assert first["observations"] == [] and len(first["published_calls"]) == 1
    assert first["published_calls"][0]["call_id"] == "call_00"
    assert first["coverage"]["published_call_page"] == {
        "offset": 0, "shown": 1, "total": 24,
        "source": "physical_task_result_trace_refs",
    }
    assert first["has_more"] is True and first["cursor"] is not None

    tampered = copy.deepcopy(first["cursor"])
    tampered["published_calls"]["offset"] = 0
    refused, data = _call(
        ctx, task_id=task_id, operation="list", stream="tools", limit=1,
        cursor=tampered,
    )
    assert refused["status"] == "error" and refused["code"] == "invalid_arguments"
    assert data is None

    _result, second = _call(
        ctx, task_id=task_id, operation="list", stream="tools", limit=1,
        cursor=first["cursor"],
    )
    assert [row["call_id"] for row in second["published_calls"]] == ["call_01"]
    assert second["coverage"]["published_call_page"]["offset"] == 1


def test_dispatch_source_stays_on_canonical_plane_when_execution_result_is_selected(tmp_path):
    from ouroboros.tool_call_log import new_invocation, persist_dispatch_source

    task_id = "dispatch-plane"
    execution = prepare_task_drive(tmp_path, task_id, "empty")
    assert execution is not None
    invocation = new_invocation("provider-call", {}, 1)
    persist_dispatch_source(
        {"budget_drive_root": str(tmp_path)}, execution / "logs", task_id,
        invocation, "run_script", {"script": "print('canonical-dispatch')"},
    )
    write_task_result(tmp_path, task_id, "running", result="not final")
    write_task_result(execution, task_id, STATUS_COMPLETED, result="execution final")

    ref = invocation["args_source_ref"]
    result, metadata = _call(
        _ctx(tmp_path), task_id=task_id, operation="read_call",
        call_id=ref["call_id"], manifest_sha256=ref["sha256"],
    )
    assert result["status"] == "ok"
    assert metadata["source"]["call_type"] == "tool_dispatch"
    assert metadata["source"]["plane"] == "canonical"


def test_trace_sources_apply_root_resource_and_presence_resource_admission(tmp_path, monkeypatch):
    task_id = "resource-bounded"
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="done")
    events = tmp_path / "logs/events.jsonl"
    _write_rows(events, [{"task_id": task_id, "type": "visible_only_if_admitted", "ts": "1"}])

    root_ctx = _ctx(tmp_path)
    root_ctx.task_contract = {"resource_policy": {"protected_artifacts": [{
        "paths": [str(events)], "role": "black_box_reference",
    }]}}
    blocked, _data = _call(root_ctx, task_id=task_id, operation="list", stream="events")
    assert blocked["status"] == "blocked" and blocked["code"] == "access_denied"
    assert "not readable by this actor" in blocked["message"]
    assert "visible_only_if_admitted" not in json.dumps(blocked)

    retained = persist_call(
        tmp_path, task_id=task_id, call_id="resource_call", call_type="tool_call",
        payload={"result": "protected projection bytes"},
    )
    write_task_result(
        tmp_path, task_id, STATUS_COMPLETED, result="done",
        trace_refs={"tool_call_refs": [{"manifest_ref": retained["manifest_ref"]}]},
    )
    root_ctx.task_contract = {"resource_policy": {"protected_artifacts": [{
        "paths": [retained["manifest_ref"]["path"]], "role": "black_box_reference",
    }]}}
    manifest_blocked, _data = _call(
        root_ctx, task_id=task_id, operation="read_call", call_id="resource_call",
        manifest_sha256=retained["manifest_ref"]["sha256"],
    )
    assert manifest_blocked["status"] == "blocked" and manifest_blocked["code"] == "access_denied"
    assert "protected projection bytes" not in json.dumps(manifest_blocked)

    root_ctx.task_contract = {"resource_policy": {"protected_artifacts": [{
        "paths": [retained["redacted_projection_ref"]["path"]], "role": "black_box_reference",
    }]}}
    blob_blocked, _data = _call(
        root_ctx, task_id=task_id, operation="read_call", call_id="resource_call",
        manifest_sha256=retained["manifest_ref"]["sha256"],
    )
    assert blob_blocked["status"] == "blocked" and blob_blocked["code"] == "access_denied"
    assert "protected projection bytes" not in json.dumps(blob_blocked)

    import ouroboros.presence_authority as presence
    from ouroboros.presence_authority import presence_ceiling_payload
    from tests.frozen_presence_authority import build_presence_capability_ceiling
    from tests.frozen_presence_capabilities import PresenceProfileResolution, PresenceSelection, PresenceToolTarget
    from tests.frozen_presence_runtime import ResolvedPresenceRuntime

    resolution = PresenceProfileResolution(
        active=(PresenceSelection("1" * 64, PresenceToolTarget("builtin", "query_records")),),
        missing_required=(), missing_optional=(), orphaned=(),
        runtime=ResolvedPresenceRuntime("main", 10, 10, False),
        profile_fingerprint="a" * 64, selection_fingerprint="b" * 64,
        required_selections_present=True,
    )
    ceiling = build_presence_capability_ceiling(
        skill_name="trace-presence", skill_content_hash="c" * 64,
        state_fingerprint="d" * 64, resolution=resolution,
    )
    presence_ctx = _ctx(tmp_path)
    presence_ctx.task_contract = {"capability_ceiling": presence_ceiling_payload(ceiling)}
    monkeypatch.setattr(presence, "presence_caller_binding", lambda _ctx: "binding")
    monkeypatch.setattr(presence, "presence_work_refusal", lambda *_a, **_kw: "")
    presence_blocked, _data = _call(
        presence_ctx, task_id=task_id, operation="list", stream="events",
        presence_scope="own_binding",
    )
    assert presence_blocked["status"] == "blocked"
    assert "Presence resource ceiling does not include this read" in presence_blocked["message"]


def test_authoritative_selection_never_promotes_an_equal_earlier_draft(tmp_path):
    task_id = "authored"
    exact = "the same bytes"
    payload = {"message": exact}
    response = persist_call(tmp_path, task_id=task_id, call_id="llm_1_response",
                            call_type="llm_response", payload=payload)
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result=exact, terminal_origin="model_final",
                      trace_refs={"llm_call_refs": [{"llm_call_id": "llm_1",
                                                       "response_ref": response["manifest_ref"]}]})
    ctx = _ctx(tmp_path)
    _result, page = _call(ctx, task_id=task_id, operation="list", stream="authored_outputs")
    selected, draft = page["outputs"]
    assert selected["authored_output_id"] == "authoritative_result" and selected["selected"] is True
    assert draft["selected"] is False and draft["selection_basis"] == "observed_llm_response"

    _result, draft_meta = _call(ctx, task_id=task_id, operation="read_authored_output",
                                authored_output_id=draft["authored_output_id"])
    _result, draft_source = _call(
        ctx, task_id=task_id, operation="read_authored_output", authored_output_id=draft["authored_output_id"],
        source_start_char=0, source_end_char=draft_meta["source"]["complete_chars"],
    )
    _result, final_meta = _call(ctx, task_id=task_id, operation="read_authored_output",
                                authored_output_id="authoritative_result")
    _result, final_source = _call(
        ctx, task_id=task_id, operation="read_authored_output", authored_output_id="authoritative_result",
        source_start_char=0, source_end_char=final_meta["source"]["complete_chars"],
    )
    assert draft_source["source"]["text"] == final_source["source"]["text"] == exact
    assert draft_source["source"]["selected"] is False


def test_settled_canonical_result_outranks_a_richer_stale_execution_replica(tmp_path):
    task_id = "conflicting-replicas"
    execution = prepare_task_drive(tmp_path, task_id, "empty")
    assert execution is not None
    stale = persist_call(
        execution, task_id=task_id, call_id="stale_response",
        call_type="llm_response", payload={"message": "stale execution answer"},
    )
    write_task_result(
        execution, task_id, STATUS_COMPLETED, result="stale execution answer",
        terminal_origin="model_final",
        trace_refs={"llm_call_refs": [{"llm_call_id": "stale", "response_ref": stale["manifest_ref"]}]},
    )
    # The canonical row is deliberately less trace-rich, so the former score
    # heuristic selected the stale execution copy despite its older answer.
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="canonical final answer")

    ctx = _ctx(tmp_path)
    _result, listed = _call(ctx, task_id=task_id, operation="list", stream="authored_outputs")
    assert len(listed["outputs"]) == 1
    assert listed["outputs"][0]["authored_output_id"] == "authoritative_result"
    canonical_sha = hashlib.sha256(b"canonical final answer").hexdigest()
    assert listed["outputs"][0]["answer_sha256"] == canonical_sha
    _meta_result, metadata = _call(
        ctx, task_id=task_id, operation="read_authored_output",
        authored_output_id="authoritative_result",
    )
    _source_result, source = _call(
        ctx, task_id=task_id, operation="read_authored_output",
        authored_output_id="authoritative_result", source_start_char=0,
        source_end_char=metadata["source"]["complete_chars"],
    )
    assert source["source"]["text"] == "canonical final answer"


def test_invalid_canonical_authority_never_falls_back_to_a_stale_execution_answer(tmp_path):
    task_id = "occupied-canonical"
    legacy = tmp_path / "task_results" / f"{task_id}.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"{")
    store_import.ensure_current_store(tmp_path, with_children=False)

    execution = prepare_task_drive(tmp_path, task_id, "empty")
    assert execution is not None
    write_task_result(
        execution, task_id, STATUS_COMPLETED,
        result="STALE-EXECUTION-MUST-NOT-BECOME-AUTHORITY",
    )
    result, data = _call(
        _ctx(tmp_path), task_id=task_id, operation="list", stream="authored_outputs",
    )
    assert result["status"] == "error" and result["code"] == "query_failed"
    assert data is None
    assert "STALE-EXECUTION-MUST-NOT-BECOME-AUTHORITY" not in json.dumps(result)


def test_running_task_has_observed_drafts_but_no_selected_final(tmp_path):
    task_id = "still-running"
    response = persist_call(
        tmp_path, task_id=task_id, call_id="llm_running_response",
        call_type="llm_response", payload={"message": "draft only"},
    )
    write_task_result(tmp_path, task_id, "running", result="not authoritative", trace_refs={
        "llm_call_refs": [{"llm_call_id": "llm_running", "response_ref": response["manifest_ref"]}],
    })
    ctx = _ctx(tmp_path)
    _result, page = _call(ctx, task_id=task_id, operation="list", stream="authored_outputs")
    assert page["outputs"] and all(row["selected"] is False for row in page["outputs"])
    assert page["coverage"]["selection_rule"].startswith("no settled authoritative result")
    unavailable, _data = _call(
        ctx, task_id=task_id, operation="read_authored_output",
        authored_output_id="authoritative_result",
    )
    assert unavailable["status"] == "unavailable" and unavailable["code"] == "not_found"


def test_authored_source_withholds_private_reasoning_and_llm_request_is_not_a_call(tmp_path):
    task_id = "authored-policy"
    request = persist_call(
        tmp_path, task_id=task_id, call_id="llm_private_request", call_type="llm_request",
        payload={"messages": [{"role": "system", "content": "PRIVATE-SYSTEM-PROMPT"}]},
    )
    response = persist_call(
        tmp_path, task_id=task_id, call_id="llm_public_response", call_type="llm_response",
        payload={
            "message": {
                "role": "assistant", "content": [
                    {"type": "text", "text": "Visible answer."},
                    {"type": "thinking", "text": "PRIVATE-BLOCK"},
                    {"text": "PRIVATE-GEMINI-THOUGHT", "thought": True},
                ],
                "reasoning_content": "PRIVATE-REASONING-CONTENT",
                "reasoning_details": [{"type": "reasoning.text", "text": "PRIVATE-DETAIL"}],
            },
            "usage": {"provider_private": "PRIVATE-USAGE"},
        },
    )
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="Visible answer.", trace_refs={
        "llm_call_refs": [{
            "llm_call_id": "llm_public", "request_ref": request["manifest_ref"],
            "response_ref": response["manifest_ref"],
        }],
    })
    ctx = _ctx(tmp_path)

    _result, tools = _call(ctx, task_id=task_id, operation="list", stream="tools")
    assert tools["published_calls"] == []
    denied, _data = _call(
        ctx, task_id=task_id, operation="read_call", call_id="llm_private_request",
        manifest_sha256=request["manifest_ref"]["sha256"],
    )
    assert denied["status"] == "blocked" and denied["code"] == "access_denied"

    _result, authored = _call(ctx, task_id=task_id, operation="list", stream="authored_outputs")
    draft = next(row for row in authored["outputs"] if not row["selected"])
    _result, metadata = _call(
        ctx, task_id=task_id, operation="read_authored_output",
        authored_output_id=draft["authored_output_id"],
    )
    _result, source = _call(
        ctx, task_id=task_id, operation="read_authored_output",
        authored_output_id=draft["authored_output_id"], source_start_char=0,
        source_end_char=metadata["source"]["complete_chars"],
    )
    encoded = json.dumps(source)
    assert "Visible answer." in source["source"]["text"]
    for private in (
        "PRIVATE-REASONING-CONTENT", "PRIVATE-DETAIL", "PRIVATE-BLOCK",
        "PRIVATE-GEMINI-THOUGHT", "PRIVATE-USAGE",
    ):
        assert private not in encoded
    assert source["source"]["projection"] == "public_authored_message_without_provider_reasoning"


def test_read_call_verifies_decoded_task_call_and_family_before_serving_projection(tmp_path):
    task_id = "manifest-identity"
    expected = persist_call(
        tmp_path, task_id=task_id, call_id="expected_call", call_type="tool_call",
        payload={"result": "EXPECTED"},
    )
    foreign_call = persist_call(
        tmp_path, task_id=task_id, call_id="other_call", call_type="tool_call",
        payload={"result": "OTHER-CALL-MUST-NOT-BE-SERVED"},
    )
    wrong_family = persist_call(
        tmp_path, task_id=task_id, call_id="response_in_tool_slot", call_type="llm_response",
        payload={"message": "LLM-RESPONSE-MUST-NOT-BE-SERVED-AS-TOOL"},
    )
    swapped_ref = {
        **foreign_call["manifest_ref"],
        # The published address claims the requested call while its physical
        # manifest and digest belong to another call.
        "call_id": expected["manifest_ref"]["call_id"],
    }
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="done", trace_refs={
        "tool_call_refs": [
            {"manifest_ref": swapped_ref},
            {"manifest_ref": wrong_family["manifest_ref"]},
        ],
    })
    ctx = _ctx(tmp_path)

    identity_failed, _data = _call(
        ctx, task_id=task_id, operation="read_call", call_id="expected_call",
        manifest_sha256=foreign_call["manifest_ref"]["sha256"],
    )
    family_failed, _data = _call(
        ctx, task_id=task_id, operation="read_call", call_id="response_in_tool_slot",
        manifest_sha256=wrong_family["manifest_ref"]["sha256"],
    )
    for failed, forbidden in (
        (identity_failed, "OTHER-CALL-MUST-NOT-BE-SERVED"),
        (family_failed, "LLM-RESPONSE-MUST-NOT-BE-SERVED-AS-TOOL"),
    ):
        assert failed["status"] == "error" and failed["code"] == "query_failed"
        assert forbidden not in json.dumps(failed)


def test_existing_manifest_reader_adds_optional_physical_admission_and_size_without_changing_default(tmp_path):
    from ouroboros.observability import read_call_manifest_ref

    retained = persist_call(
        tmp_path, task_id="reader-options", call_id="bounded_manifest", call_type="tool_call",
        payload={"result": "visible"},
    )
    ref = retained["manifest_ref"]
    assert read_call_manifest_ref(tmp_path, ref, task_id="reader-options")["call_id"] == "bounded_manifest"
    admitted = []
    bounded = read_call_manifest_ref(
        tmp_path, ref, task_id="reader-options", max_bytes=16 * 1024,
        admit=lambda path: admitted.append(Path(path)), call_types=("tool_call",),
    )
    assert bounded["call_type"] == "tool_call" and admitted == [Path(ref["path"])]
    with pytest.raises(PermissionError, match="controlled admission refusal"):
        read_call_manifest_ref(
            tmp_path, ref, task_id="reader-options", max_bytes=16 * 1024,
            admit=lambda _path: (_ for _ in ()).throw(PermissionError("controlled admission refusal")),
        )
    with pytest.raises(ValueError, match="byte limit"):
        read_call_manifest_ref(tmp_path, ref, task_id="reader-options", max_bytes=8)


def test_source_range_errors_are_typed_and_raw_only_legacy_manifest_is_unavailable(tmp_path):
    from ouroboros.observability import write_blob, write_call_manifest

    task_id = "source-errors"
    visible = persist_call(tmp_path, task_id=task_id, call_id="visible", call_type="tool_call",
                           payload={"result": "bounded"})
    corrupt = persist_call(tmp_path, task_id=task_id, call_id="corrupt", call_type="tool_call",
                           payload={"result": "must fail verification"})
    raw_ref = write_blob(tmp_path, {"token": "RAW-ONLY"})
    raw_manifest = write_call_manifest(
        tmp_path, task_id=task_id, call_id="raw_only",
        manifest={"call_type": "tool_call", "full_payload_ref": raw_ref, "full_payload_redacted": False},
    )
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="done", trace_refs={
        "tool_call_refs": [
            {"manifest_ref": visible["manifest_ref"]},
            {"manifest_ref": corrupt["manifest_ref"]},
            {"manifest_ref": raw_manifest},
        ],
    })
    ctx = _ctx(tmp_path)
    invalid, _data = _call(
        ctx, task_id=task_id, operation="read_call", call_id="visible",
        manifest_sha256=visible["manifest_ref"]["sha256"], source_start_char=0, source_end_char=10_000,
    )
    assert invalid["status"] == "error" and invalid["code"] == "invalid_arguments"
    assert "outside complete_chars=" in invalid["message"] and "text" not in invalid

    unavailable, _data = _call(
        ctx, task_id=task_id, operation="read_call", call_id="raw_only",
        manifest_sha256=raw_manifest["sha256"],
    )
    assert unavailable["status"] == "unavailable" and unavailable["code"] == "not_found"
    assert "no redacted projection" in unavailable["message"]
    assert "RAW-ONLY" not in json.dumps(unavailable)

    Path(corrupt["redacted_projection_ref"]["path"]).write_bytes(b"corrupt-cas-bytes")
    failed, _data = _call(
        ctx, task_id=task_id, operation="read_call", call_id="corrupt",
        manifest_sha256=corrupt["manifest_ref"]["sha256"],
    )
    assert failed["status"] == "error" and failed["code"] == "query_failed"
    assert failed["message"] == "task_trace retained source is unreadable or failed verification"
    assert str(tmp_path) not in json.dumps(failed)


def test_presence_scope_propagates_to_published_dispatch_call_and_authored_recipes(tmp_path, monkeypatch):
    import ouroboros.presence_authority as presence
    from ouroboros.tool_call_log import invocation_fields, new_invocation, persist_dispatch_source

    task_id = "presence-recipes"
    invocation = new_invocation("provider-call", {}, 1)
    persist_dispatch_source(
        {"budget_drive_root": str(tmp_path)}, tmp_path / "logs", task_id,
        invocation, "run_script", {"script": "print('recover-me')"},
    )
    _write_rows(tmp_path / "logs/tools.jsonl", [{
        "task_id": task_id, "type": "tool_call_started", "tool": "run_script",
        **invocation_fields(invocation),
    }])
    tool = persist_call(
        tmp_path, task_id=task_id, call_id="tool_result", call_type="tool_call",
        payload={"result": "done"},
    )
    response = persist_call(
        tmp_path, task_id=task_id, call_id="authored_response", call_type="llm_response",
        payload={"message": "draft"},
    )
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="final", trace_refs={
        "tool_call_refs": [{"manifest_ref": tool["manifest_ref"]}],
        "llm_call_refs": [{"llm_call_id": "llm", "response_ref": response["manifest_ref"]}],
    })
    monkeypatch.setattr(presence, "presence_work_refusal", lambda *_a, **_kw: "")
    ctx = _ctx(tmp_path, task_id, presence={"binding_id": "binding"})

    _result, tools = _call(
        ctx, task_id=task_id, operation="list", stream="tools", presence_scope="own_binding",
    )
    recipes = [row["source_read"] for row in tools["published_calls"]]
    recipes += [row["dispatch_source"]["source_read"] for row in tools["observations"]
                if "dispatch_source" in row]
    assert len(recipes) == 2
    assert all(recipe["arguments"]["presence_scope"] == "own_binding" for recipe in recipes)
    dispatch = next(row["dispatch_source"] for row in tools["observations"]
                    if "dispatch_source" in row)
    assert dispatch["manifest_sha256"] == invocation["args_source_ref"]["sha256"]

    _result, authored = _call(
        ctx, task_id=task_id, operation="list", stream="authored_outputs",
        presence_scope="own_binding",
    )
    assert all(row["source_read"]["arguments"]["presence_scope"] == "own_binding"
               for row in authored["outputs"])
    _result, authoritative = _call(
        ctx, task_id=task_id, operation="read_authored_output",
        authored_output_id="authoritative_result", presence_scope="own_binding",
    )
    assert authoritative["source"]["current_reread"]["arguments"]["presence_scope"] == "own_binding"


def test_authorization_admits_store_and_presence_queue_before_ownership_reads(tmp_path, monkeypatch):
    import ouroboros.presence_authority as presence
    from ouroboros.tools import query_data

    task_id = "admission-order"
    write_task_result(tmp_path, task_id, STATUS_COMPLETED, result="done")
    ctx = _ctx(tmp_path, task_id, presence={"binding_id": "binding"})
    admitted = []

    def admit(_ctx, target):
        admitted.append(Path(target).name)
        return ""

    def ownership(*_args, **_kwargs):
        assert admitted[:2] == ["current.sqlite", "queue_snapshot.json"]
        return "controlled refusal"

    monkeypatch.setattr(query_data, "_read_refusal", admit)
    monkeypatch.setattr(presence, "presence_work_refusal", ownership)
    blocked, _data = _call(
        ctx, task_id=task_id, operation="list", stream="events",
        presence_scope="own_binding",
    )
    assert blocked["status"] == "blocked" and "controlled refusal" in blocked["message"]


def test_presence_store_binding_does_not_require_admission_of_an_unused_queue_fallback(tmp_path):
    task_id = "stored-presence-binding"
    write_task_result(
        tmp_path, task_id, STATUS_COMPLETED, result="bound answer",
        metadata={"presence": {"binding_id": "binding"}},
    )
    ctx = _ctx(tmp_path, task_id, presence={"binding_id": "binding"})
    ctx.task_contract = {"resource_policy": {"protected_artifacts": [{
        "paths": [str(tmp_path / "state/queue_snapshot.json")],
        "role": "black_box_reference",
    }]}}
    result, authored = _call(
        ctx, task_id=task_id, operation="list", stream="authored_outputs",
        presence_scope="own_binding",
    )
    assert result["status"] == "ok"
    assert authored["outputs"][0]["authored_output_id"] == "authoritative_result"


def test_sibling_presence_and_native_pin_negative_controls(tmp_path, monkeypatch):
    store_import.ensure_current_store(tmp_path, with_children=False)
    for task_id, parent in (("parent", ""), ("left", "parent"), ("right", "parent")):
        store.update_task(tmp_path, task_id, lambda _old, tid=task_id, par=parent: {
            "task_id": tid, "status": "completed", "parent_task_id": par, "root_task_id": "parent",
            "result": tid,
        })
    child_ctx = _ctx(tmp_path, "left", parent_task_id="parent", delegation_role="subagent",
                     root_task_id="parent")
    blocked, _data = _call(child_ctx, task_id="right", operation="list", stream="events")
    assert blocked["status"] == "blocked" and blocked["code"] == "access_denied"

    import ouroboros.presence_authority as presence
    monkeypatch.setattr(presence, "presence_caller_binding", lambda _ctx: "binding")
    monkeypatch.setattr(presence, "presence_work_refusal", lambda *_a, **_kw: "foreign binding")
    presence_blocked, _data = _call(child_ctx, task_id="left", operation="list", stream="events")
    assert presence_blocked["status"] == "blocked" and "requires presence_scope=own_binding" in presence_blocked["message"]

    monkeypatch.setattr(presence, "presence_work_refusal", lambda *_a, **_kw: "")
    presence_allowed, _data = _call(
        child_ctx, task_id="right", operation="list", stream="events",
        presence_scope="own_binding",
    )
    assert presence_allowed["status"] == "ok"  # binding scope, not child-lineage scope

    monkeypatch.setattr(presence, "presence_caller_binding", lambda _ctx: None)
    pin = tmp_path / "pin"
    pin.mkdir()
    native = ToolContext(repo_dir=child_ctx.repo_dir, drive_root=tmp_path, task_id="parent",
                         task_metadata={"native_data_root": str(pin), "budget_drive_root": str(tmp_path)})
    unavailable, _data = _call(native, task_id="parent", operation="list", stream="events")
    assert unavailable["status"] == "unavailable" and unavailable["code"] == "not_found"


def test_real_native_inspection_registry_preserves_child_lineage_and_refuses_sibling_trace(tmp_path):
    from ouroboros.review_native_episode import inspection_registry
    from ouroboros.usage_accounting import UsageScope, usage_scope

    store_import.ensure_current_store(tmp_path, with_children=False)
    for task_id, parent in (("parent", ""), ("left", "parent"), ("right", "parent")):
        store.update_task(tmp_path, task_id, lambda _old, tid=task_id, par=parent: {
            "task_id": tid, "status": "completed", "parent_task_id": par,
            "root_task_id": "parent", "delegation_role": "subagent" if par else "root",
            "result": tid,
        })
    repo = tmp_path / "repo"
    repo.mkdir()
    scope = UsageScope(
        drive_root=tmp_path, task_id="left", root_task_id="parent", parent_task_id="parent",
    )
    with usage_scope(scope):
        registry, inspection, _schemas = inspection_registry(str(repo), tmp_path, "reviewer-label")

    assert inspection.task_id == "left"
    assert inspection.task_metadata["parent_task_id"] == "parent"
    assert inspection.task_metadata["delegation_role"] == "subagent"
    result = registry.execute_result("query_records", {
        "form": "task_trace", "task_id": "right", "operation": "list", "stream": "events",
    })
    payload = json.loads(result.text)
    assert result.status == "blocked" and payload["code"] == "access_denied"
    assert "outside this delegated actor" in payload["message"]


def test_native_pin_allows_own_exact_source_but_never_live_or_sibling(tmp_path, monkeypatch):
    live, pin = tmp_path / "live", tmp_path / "native-pin"
    live.mkdir()
    pin.mkdir()
    for root in (live, pin):
        store_import.ensure_current_store(root, with_children=False)

    pinned = persist_call(
        pin, task_id="left", call_id="pinned_call", call_type="tool_call",
        payload={"result": "PINNED-SOURCE"},
    )
    live_call = persist_call(
        live, task_id="left", call_id="live_call", call_type="tool_call",
        payload={"result": "LIVE-SOURCE-MUST-NOT-APPEAR"},
    )
    stale_child = live / "task_drives/left"
    stale_child.mkdir(parents=True)
    write_task_result(stale_child, "left", STATUS_COMPLETED, result="stale mapped answer")
    _write_rows(stale_child / "logs/events.jsonl", [{
        "task_id": "left", "type": "stale_live_child_mapping_must_not_appear", "ts": "3",
    }])
    write_task_result(
        pin, "left", STATUS_COMPLETED, result="pinned answer", parent_task_id="parent",
        root_task_id="parent", delegation_role="subagent",
        child_drive_root=str(stale_child), headless_child_drive_root=str(stale_child),
        trace_refs={"tool_call_refs": [{"manifest_ref": pinned["manifest_ref"]}]},
    )
    write_task_result(
        live, "left", STATUS_COMPLETED, result="live answer", parent_task_id="parent",
        root_task_id="parent", delegation_role="subagent",
        trace_refs={"tool_call_refs": [{"manifest_ref": live_call["manifest_ref"]}]},
    )
    write_task_result(
        pin, "right", STATUS_COMPLETED, result="sibling", parent_task_id="parent",
        root_task_id="parent", delegation_role="subagent",
    )
    _write_rows(pin / "logs/events.jsonl", [{
        "task_id": "left", "type": "pinned_event", "ts": "1",
    }])
    _write_rows(live / "logs/events.jsonl", [{
        "task_id": "left", "type": "live_event_must_not_appear", "ts": "2",
    }])
    repo = live / "repo"
    repo.mkdir(exist_ok=True)
    ctx = ToolContext(
        repo_dir=repo, drive_root=pin, budget_drive_root=str(live), task_id="left",
        task_metadata={
            "native_data_root": str(pin), "budget_drive_root": str(live),
            "parent_task_id": "parent", "root_task_id": "parent",
            "delegation_role": "subagent",
        },
    )
    # Simulate a stale resolver honoring the absolute child mapping. Native
    # trace root selection must return before consulting this live resolver.
    import ouroboros.task_custody as task_custody
    original_drives = task_custody.own_child_drives
    monkeypatch.setattr(
        task_custody, "own_child_drives",
        lambda root, task: [stale_child] if Path(root).resolve() == pin.resolve()
        else original_drives(root, task),
    )

    listed_result, listed = _call(ctx, task_id="left", operation="list", stream="events")
    assert listed_result["status"] == "ok" and listed["coverage"]["plane"] == "native_pin", listed_result
    encoded = json.dumps(listed)
    assert "pinned_event" in encoded and "live_event_must_not_appear" not in encoded
    assert "stale_live_child_mapping_must_not_appear" not in encoded

    _meta_result, metadata = _call(
        ctx, task_id="left", operation="read_call", call_id="pinned_call",
        manifest_sha256=pinned["manifest_ref"]["sha256"],
    )
    source_result, source = _call(
        ctx, task_id="left", operation="read_call", call_id="pinned_call",
        manifest_sha256=pinned["manifest_ref"]["sha256"], source_start_char=0,
        source_end_char=metadata["source"]["complete_chars"],
    )
    assert source_result["status"] == "ok" and "PINNED-SOURCE" in source["source"]["text"]
    assert "LIVE-SOURCE-MUST-NOT-APPEAR" not in json.dumps(source)

    denied, _data = _call(ctx, task_id="right", operation="list", stream="events")
    assert denied["status"] == "blocked" and denied["code"] == "access_denied"
    assert "outside this delegated actor" in denied["message"]
