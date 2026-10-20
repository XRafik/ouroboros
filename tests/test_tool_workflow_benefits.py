"""Synthetic consumer comparisons with the retained compatibility routes.

A valid old one-shell workflow may perform several ``gh`` commands, including
prechecks and readback. These tests make no model, time, or money claim.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy

import pytest

from ouroboros.contracts.task_constraint import TaskConstraint
from ouroboros.observability import persist_call
from ouroboros.task_results import write_task_result
from ouroboros.tools import (
    control_task_results,
    github,
    github_pr_write,
    github_workflows,
    join_ledger,
    media,
    query_data,
)
from ouroboros.tools.registry import ToolContext, ToolRegistry
from tests.test_github_pr_write import BASE_SHA, CREATE, SHA, FakeGitHub, _open_pr
from tests.test_github_workflows import _DIST, LOG, FakeGh, _retained, _zip
from tests.test_tool_usability_slice import _write_pdf


def test_vcs_read_reaches_git_identity_with_old_readonly_access(tmp_path, monkeypatch):
    from ouroboros.tools.tool_resolution import _build_builtin_target_binding
    from ouroboros.tools.vcs_read import _vcs_read

    repo, data = tmp_path / "repo", tmp_path / "data"
    repo.mkdir()
    data.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    ctx = ToolContext(repo_dir=repo, drive_root=data, task_id="reader",
                      task_constraint=TaskConstraint(mode="local_readonly_subagent", allow_enable=False))
    registry = ToolRegistry(repo, data)
    registry.set_context(ctx)
    monkeypatch.setattr("ouroboros.safety.check_safety", lambda *_a, **_k: (True, ""))
    assert registry.get_schema_by_name("run_command") is None  # old shell route cannot be used by this actor
    assert registry.get_schema_by_name("vcs_read") is not None
    binding = _build_builtin_target_binding(ctx, "vcs_read", {"root": "active_workspace", "action": "identity"})
    answer = _vcs_read(ctx, root="active_workspace", action="identity", _resolved_binding=binding)
    assert json.loads(answer.split("\n\nVCS target:", 1)[0])["worktree"] == str(repo)


def test_query_sql_and_records_keep_old_answers_with_narrower_grammar(tmp_path):
    from ouroboros import store, store_import

    store_import.ensure_current_store(tmp_path, with_children=False)
    store.update_task(tmp_path, "caller", lambda _old: {"task_id": "caller", "status": "completed", "result": "ok"})
    repo = tmp_path / "repo"
    repo.mkdir()
    ctx = ToolContext(repo_dir=repo, drive_root=tmp_path, task_id="caller")
    args = {"db": "current", "query": "SELECT task_id,status FROM tasks ORDER BY task_id"}
    old_sql = json.loads(query_data._query_data(ctx, op="sql", **args))
    new_sql = json.loads(query_data._query_sql(ctx, **args))
    assert new_sql == old_sql and new_sql["status"] == "ok"
    document = tmp_path / "state/queue_snapshot.json"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text('{"rows":[{"safe":1,"hidden":"VALUE"}]}', encoding="utf-8")
    old_doc = json.loads(query_data._query_data(ctx, op="json", kind="queue_snapshot", select="rows[0].safe"))
    new_doc = json.loads(query_data._query_records(ctx, form="document", kind="queue_snapshot", select="rows[0].safe"))
    assert new_doc == old_doc and new_doc["data"] == 1
    missing = json.loads(query_data._query_records(ctx, form="document", kind="queue_snapshot", select="rows[0].missing"))
    assert missing["status"] == "error" and "segment 'missing'" in missing["message"]
    assert "VALUE" not in missing["message"]
    old_schema, sql_schema, record_schema = [x.schema["parameters"] for x in query_data.get_tools()]
    assert old_schema["required"] == ["op"]
    assert sql_schema["required"] == ["query"] and sql_schema["additionalProperties"] is False
    assert record_schema["required"] == ["form"] and record_schema["additionalProperties"] is False
    assert "operation" in record_schema["properties"]  # typed task-trace route absent from the old op enum
    assert "task_trace" not in old_schema["properties"]["op"]["enum"]


def test_query_records_resolves_retained_prior_call_from_published_identity(tmp_path):
    from tests.test_query_records_task_trace import _ctx

    trace = persist_call(tmp_path, task_id="caller", call_id="call-1", call_type="tool_call",
                         payload={"tool": "demo", "result": "published"}, keep_raw=True)
    write_task_result(tmp_path, "caller", "completed", result="done", terminal_origin="model_final",
                      trace_refs={"tool_call_refs": [{"manifest_ref": trace["manifest_ref"],
                                                       "redacted_projection_ref": trace["redacted_projection_ref"]}]})
    ctx = _ctx(tmp_path, task_id="caller")
    old = json.loads(query_data._query_data(ctx, op="json", kind="task_result", ids=["caller"]))
    assert old["status"] == "ok"
    ref = old["data"]["trace_refs"]["tool_call_refs"][0]["redacted_projection_ref"]
    old_blob = json.loads(query_data._query_data(
        ctx, op="blob", sha256=ref["sha256"], blob_kind="json",
    ))
    assert old_blob["status"] == "ok" and "published" in json.dumps(old_blob["data"])
    listed = json.loads(query_data._query_records(ctx, form="task_trace", task_id="caller", operation="list", stream="tools"))
    assert listed["status"] == "ok"
    call = next(row for row in listed["data"]["published_calls"] if row["call_id"] == "call-1")
    read = json.loads(query_data._query_records(ctx, form="task_trace", task_id="caller", operation="read_call",
                                                  call_id="call-1", manifest_sha256=call["manifest_sha256"]))
    assert read["status"] == "ok" and read["data"]["source"]["complete_chars"] > 0
    content = json.loads(query_data._query_records(
        ctx, form="task_trace", task_id="caller", operation="read_call", call_id="call-1",
        manifest_sha256=call["manifest_sha256"], source_start_char=0,
        source_end_char=read["data"]["source"]["complete_chars"],
    ))
    assert content["status"] == "ok" and "published" in content["data"]["source"]["text"]
    # Both routes reach the redacted projection. The new route binds call_id plus
    # manifest digest and returns a typed source range instead of caller-followed refs.


def test_result_views_keep_handoff_facts_in_fewer_answer_chars(tmp_path):
    from tests.test_task_result_views_and_sleep_until import _ctx, _write

    _write(tmp_path, terminal_host_notice="Host still owns one limitation.")
    ctx = _ctx(tmp_path)
    full = control_task_results._get_task_result(ctx, "child")  # OLD155cffe route
    answer = json.loads(control_task_results._get_task_result(ctx, "child", view="answer"))
    summary = json.loads(control_task_results._get_task_result(ctx, "child", view="summary"))
    evidence = json.loads(control_task_results._get_task_result(ctx, "child", view="evidence"))
    assert len(json.dumps(answer)) < len(full)
    assert answer["answer"] == "Exact authored answer."
    assert answer["answer_sha256"] == hashlib.sha256(answer["answer"].encode()).hexdigest()
    assert answer["terminal_origin"] == "model_final" and answer["nonclean_terminal_host_notice"]
    assert answer["capability_delta"]["reduced"] is True
    assert summary["cost"]["accounted_upper_bound_usd"] == 1.25
    assert summary["delegated_custody"]["open_run_ids"] == ["run-a"]
    assert evidence["projection_refs"] and all(x["kind"] == "current_reread_recipe" for x in evidence["projection_refs"])


def test_sleep_until_enters_same_event_wait_without_old_in_slot_branch(tmp_path, monkeypatch):
    from ouroboros import model_sleep
    from tests.test_task_result_views_and_sleep_until import _ctx

    monkeypatch.setattr(model_sleep, "selectors", lambda _ctx, **chosen: chosen)
    monkeypatch.setattr(model_sleep, "request_sleep", lambda _ctx, selected, mode: {"selected": selected, "mode": mode})
    ctx = _ctx(tmp_path)
    old = control_task_results._await_messages(ctx, timeout_sec=0, tasks=["child"])
    # The old in-slot route returns immediately. The old actual park requires a separate mode choice.
    old_park = control_task_results._await_as_sleep(ctx, "warm", tasks=["child"])
    new = control_task_results._sleep_until(ctx, tasks=["child"])
    assert old != new and json.loads(new) == json.loads(old_park)
    schema = control_task_results.sleep_until_entry().schema["parameters"]
    assert "timeout_sec" not in schema["properties"] and schema["properties"]["mode"]["default"] == "warm"


def test_decide_child_results_is_exact_old_decision_with_decision_only_schema(tmp_path):
    from types import SimpleNamespace

    from ouroboros.task_status import load_effective_task_result
    from ouroboros.tools.join_ledger import _child_result_sha256
    from ouroboros.tools.task_tree import _tree_note
    from ouroboros.tools.task_tree import get_tools as tree_tools
    from tests._delivery_candidate_shared import write_child

    def fixture(label):
        root = tmp_path / label
        root.mkdir()
        write_child(root)
        ctx = SimpleNamespace(drive_root=root, budget_drive_root=root,
                              task_id="parent1", task_metadata={"root_task_id": "parent1"})
        row = {"child_task_id": "child1", "disposition": "integrated",
               "child_result_sha256": _child_result_sha256(load_effective_task_result(root, "child1"))}
        return ctx, row

    old_ctx, old_row = fixture("old")
    new_ctx, new_row = fixture("new")
    old = _tree_note(old_ctx, "decision", "Used the findings",
                     payload={"type": "child_result_disposition", "children": [old_row]})
    new = join_ledger._decide_child_results(new_ctx, [new_row], "Used the findings")
    assert "OK:" in old and "OK:" in new
    assert "idempotent" not in old.lower() and "idempotent" not in new.lower()
    schema = next(x.schema["parameters"] for x in join_ledger.get_tools() if x.name == "decide_child_results")
    old_children = tree_tools()[0].schema["parameters"]["properties"]["payload"]["properties"]["children"]
    assert schema["properties"]["children"] == old_children
    assert set(schema["properties"]) == {"children", "reason"} and schema["required"] == ["children", "reason"]


def test_extract_pdf_text_selects_late_page_and_discloses_recovery(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    path = _write_pdf(tmp_path / "pages.pdf", ["First", "", "Third", "Fourth"])
    monkeypatch.setattr(media, "_resolve_local_file", lambda *_a, **_kw: (path, ""))
    # The frozen schema exposed only path/max_pages; the current compatibility
    # spelling supplies a runnable prefix oracle without executing old code.
    old_arg_names = {"path", "max_pages"}
    new_arg_names = set(media.get_tools()[1].schema["parameters"]["properties"])
    assert new_arg_names - old_arg_names == {"pages", "start_char"}
    prefix_compat = media._ocr_pdf(None, str(path), max_pages=1)
    selected = media._ocr_pdf(None, str(path), pages="3", max_pages=1)
    assert "First" in prefix_compat and "Third" not in prefix_compat
    assert "Third" in selected and "First" not in selected
    assert "not requested" in selected and "page(s) 1-2,4" in selected
    assert "continue with pages=" in prefix_compat  # new compatibility output also names recovery


def test_gh_run_readers_add_run_identity_exact_capture_and_artifact_id(tmp_path, monkeypatch):
    from tests.test_github_project_target import _context

    ctx, _project = _context(tmp_path, "queued")
    ctx._active_builtin_tool_result = None
    driver = FakeGh(artifacts=[_DIST], artifact=_DIST, archive=_zip({"out.txt": b"ok"}))
    monkeypatch.setattr(github_workflows, "_gh_run", driver)
    # One shell invocation can run all of these gh reads and redirect stdout as
    # bytes. It can identify the same run, artifact, and exact archive correctly.
    old_run = driver(["run", "view", "11", "--json", github_workflows._RUN_FIELDS + ",jobs"], ctx)
    assert json.loads(old_run.text)["attempt"] == 1
    old_list = driver(["api", "repos/owner/selected/actions/runs/11/artifacts?per_page=100&page=1",
                       "--hostname", "github.example"], ctx)
    assert json.loads(old_list.text)["artifacts"][0]["id"] == 501
    listing = github_workflows.list_run_artifacts(ctx, run_id=11)
    assert "owner/selected run 11:" in listing and "download_github_artifact(artifact_id=501" in listing
    assert "attempt 1" not in listing  # artifact API is run-scoped, not attempt-scoped
    assert driver.kinds()[:4] == ["run_json", "artifacts", "run_json", "artifacts"]
    old_log_path = tmp_path / "old-log.bin"
    old_log = driver(["run", "view", "11", "--log", "--attempt", "1"], ctx,
                     capture_to=old_log_path, max_bytes=4096)
    assert old_log.capture.size == len(LOG) and old_log_path.read_bytes() == LOG
    log = github_workflows.get_run_log(ctx, run_id=11)
    assert "run 11 attempt 1" in log and hashlib.sha256(LOG).hexdigest() in log
    assert driver.calls[-1].args == ["run", "view", "11", "--log", "--attempt", "1"]
    assert _retained(ctx, log).read_bytes() == LOG
    old_meta = driver(["api", "repos/owner/selected/actions/artifacts/501",
                       "--hostname", "github.example"], ctx)
    assert json.loads(old_meta.text)["id"] == 501
    old_archive = driver(["api", "repos/owner/selected/actions/artifacts/501/zip",
                          "--hostname", "github.example"], ctx, capture_to=tmp_path / "old.zip", max_bytes=4096)
    assert old_archive.capture.size > 0 and (tmp_path / "old.zip").read_bytes() == driver.archive
    downloaded = github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=4096)
    assert "artifact 501" in downloaded and "out.txt" in downloaded
    assert driver.kinds()[-3:] == ["repo", "artifact", "zip"]
    assert "Retained as the archive" in downloaded
    # Benefit here is the public tool's built-in artifact-store retention,
    # digest/address and source labels, not an inability of shell to keep bytes.


def test_gh_readers_reach_readonly_child_that_cannot_use_shell(tmp_path, monkeypatch):
    from tests.test_github_project_target import _context

    ctx, _project = _context(tmp_path, "queued")
    ctx.task_constraint = TaskConstraint(mode="local_readonly_subagent", allow_enable=False)
    registry = ToolRegistry(ctx.repo_dir, ctx.drive_root)
    registry.set_context(ctx)
    monkeypatch.setattr("ouroboros.safety.check_safety", lambda *_a, **_kw: (True, ""))
    monkeypatch.setattr(github, "github_cli_configured", lambda: True)
    driver = FakeGh(artifacts=[_DIST], artifact=_DIST, archive=_zip({"out.txt": b"ok"}))
    monkeypatch.setattr(github_workflows, "_gh_run", driver)
    assert registry.get_schema_by_name("run_command") is None
    for name, args, content in (
        ("get_github_run_log", {"run_id": 11}, "run 11 attempt 1"),
        ("list_github_run_artifacts", {"run_id": 11}, "artifact_id=501"),
        ("download_github_artifact", {"artifact_id": 501, "max_bytes": 4096}, "out.txt"),
    ):
        assert registry.get_schema_by_name(name) is not None
        result = registry.execute_result(name, args)
        assert result.status == "ok" and content in result.text, (name, result.text)


def _old_one_shell_pr_workflow(driver, ctx, tool, args):
    """Body of one possible old shell invocation, with gh reads, guard, write, readback.

    The fake driver stands in for each gh subprocess. It deliberately handles
    stale heads and a lost/partial write answer, so it is a valid safe baseline.
    """
    def read(command):
        response = driver(command, ctx)
        assert response.ok, response.text
        return json.loads(response.text)

    if tool == "create":
        repo = read(["repo", "view", "--json", "nameWithOwner,url"])
        owner, name = repo["nameWithOwner"].split("/")
        head = read(["api", f"repos/{owner}/{name}/git/ref/heads/{args['head']}", "--hostname", "github.example"])
        base = read(["api", f"repos/{owner}/{name}/git/ref/heads/{args['base']}", "--hostname", "github.example"])
        if head["object"]["sha"] != args["expected_head_sha"] or base["object"]["sha"] != args["expected_base_sha"]:
            return "stale", None
        open_prs = read(["pr", "list", "--state", "open", f"--head={args['head']}",
                         f"--base={args['base']}", "--limit", "100", "--json", github_pr_write._PR_FIELDS])
        if open_prs:
            return "already_open", None
        sent = driver(["pr", "create", f"--title={args['title']}", f"--head={args['head']}",
                       f"--base={args['base']}", "--body-file=-"], ctx, input_data=args["body"])
    else:
        current = read(["pr", "view", "7", "--json", github_pr_write._PR_FIELDS])
        if current["headRefOid"] != args["expected_head_sha"] or current["state"] != "OPEN":
            return "stale", None
        if tool == "ready" and current["isDraft"] is not args["ready"]:
            return "already_held", current
        command = (["pr", "edit", "7", f"--title={args['title']}"] if tool == "edit"
                   else ["pr", "ready", "7"])
        body = args.get("body") if tool == "edit" else None
        if body is not None:
            command.append("--body-file=-")
        sent = driver(command, ctx, input_data=body)
    # A safe script inspects GitHub after the one send even if gh reports an error.
    held = read(["pr", "view", "7", "--json", github_pr_write._PR_FIELDS])
    return ("sent" if sent.ok else "answer_failed"), held


@pytest.mark.parametrize("tool,kwargs,fragment", [
    ("create", CREATE, "PR_PRECHECK_FAILED"),
    ("edit", {"number": 7, "expected_head_sha": SHA, "title": "New title"}, "PR_PRECHECK_FAILED"),
    ("ready", {"number": 7, "expected_head_sha": SHA, "ready": True}, "nothing was changed"),
])
def test_pr_writers_match_safe_one_shell_precheck_and_readback(
    tmp_path, monkeypatch, tool, kwargs, fragment,
):
    from tests.test_github_project_target import MOVED, _context

    ctx, _project = _context(tmp_path, "queued")
    ctx._active_builtin_tool_result = None
    pr = _open_pr(headRefOid=MOVED) if tool != "create" else None
    refs = {"owner:feature": MOVED, "owner:main": BASE_SHA}
    old = FakeGitHub(pr=pr, refs=refs)
    old_state, old_held = _old_one_shell_pr_workflow(old, ctx, tool, kwargs)
    assert old_state == "stale" and old_held is None and old.writes() == []
    guarded = FakeGitHub(pr=pr, refs=refs)
    monkeypatch.setattr(github_pr_write, "_gh_run", guarded)
    handler = {"create": github_pr_write.create_pr, "edit": github_pr_write.update_pr,
               "ready": github_pr_write.set_pr_ready}[tool]
    text = handler(ctx, **kwargs)
    assert fragment in text and guarded.writes() == []

    fresh_pr = None if tool == "create" else _open_pr(isDraft=True)
    fresh_refs = {"owner:feature": SHA, "owner:main": BASE_SHA}
    old_fresh = FakeGitHub(pr=fresh_pr, refs=fresh_refs)
    fresh = FakeGitHub(pr=deepcopy(fresh_pr) if fresh_pr else None, refs=fresh_refs)
    old_state, old_held = _old_one_shell_pr_workflow(old_fresh, ctx, tool, kwargs)
    assert old_state == "sent" and len(old_fresh.writes()) == 1
    monkeypatch.setattr(github_pr_write, "_gh_run", fresh)
    assert not handler(ctx, **kwargs).startswith("⚠️")
    assert len(fresh.writes()) == 1 and fresh.pr == old_held
    # Correctness parity. The new tool packages the workflow and required
    # expected SHA in its public parameters; no shell incapability is claimed.
    entry = next(x for x in github_pr_write.tool_entries() if x.name ==
                 {"create": "create_github_pr", "edit": "update_github_pr", "ready": "set_github_pr_ready"}[tool])
    assert "expected_head_sha" in entry.schema["parameters"]["required"]


def test_pr_update_reports_partial_state_after_one_send(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tests.test_github_project_target import _context

    ctx, _project = _context(tmp_path, "queued")
    ctx._active_builtin_tool_result = None
    def partial_driver():
        driver = FakeGitHub(pr=_open_pr())

        def call(args, context, **options):
            if driver.kind(args) == "edit":
                driver.calls.append(SimpleNamespace(args=list(args), repo=options.get("repo"),
                                                    input=options.get("input_data"), timeout=60))
                driver.pr["title"] = "New title"
                return github.GhResult(False, "⚠️ GH_ERROR: HTTP 422", 1, 422, "exit")
            return driver(args, context, **options)
        return driver, call

    old_driver, old_call = partial_driver()
    arguments = {"number": 7, "expected_head_sha": SHA, "title": "New title", "body": "New body"}
    old_state, old_held = _old_one_shell_pr_workflow(old_call, ctx, "edit", arguments)
    assert old_state == "answer_failed" and len(old_driver.writes()) == 1
    assert (old_held["title"], old_held["body"]) == ("New title", "Old body")

    driver, call = partial_driver()
    monkeypatch.setattr(github_pr_write, "_gh_run", call)
    text = github_pr_write.update_pr(ctx, number=7, expected_head_sha=SHA, title="New title", body="New body")
    assert len(driver.writes()) == 1 and "held: title confirmed" in text
    assert "not held: body differs" in text and "before resending only the fields not held" in text
    assert driver.pr == old_held  # typed field report packages the same correct readback


def test_frozen_and_source_registries_advertise_same_contracts(tmp_path, monkeypatch):
    import sys

    repo = tmp_path / "repo"
    repo.mkdir()
    ordinary = ToolRegistry(repo, tmp_path / "data")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    frozen = ToolRegistry(repo, tmp_path / "data")
    assert set(ordinary._base_catalog.entries) == set(frozen._base_catalog.entries)
    for name in ordinary._base_catalog.entries:
        assert ordinary._base_catalog.entries[name].schema == frozen._base_catalog.entries[name].schema


def test_query_sql_rejects_non_sql_parameters_at_contract_boundary():
    from jsonschema import ValidationError, validate

    old, sql, records = [entry.schema["parameters"] for entry in query_data.get_tools()]
    validate({"op": "sql", "query": "SELECT 1", "ids": ["unrelated"]}, old)
    with pytest.raises(ValidationError):
        validate({"query": "SELECT 1", "ids": ["unrelated"]}, sql)
    validate({"query": "SELECT 1"}, sql)
    with pytest.raises(ValidationError):
        validate({"form": "document", "kind": "queue_snapshot", "query": "SELECT 1"}, records)


def test_decision_reason_limit_is_visible_before_dispatch():
    from jsonschema import ValidationError, validate

    from ouroboros.tools.task_tree import get_tools as tree_tools

    reason = "x" * 501
    row = {"child_task_id": "child", "child_result_sha256": "a" * 64, "disposition": "integrated"}
    old = tree_tools()[0].schema["parameters"]
    decision = next(entry for entry in join_ledger.get_tools() if entry.name == "decide_child_results")
    validate({"kind": "decision", "text": reason,
              "payload": {"type": "child_result_disposition", "children": [row]}}, old)
    with pytest.raises(ValidationError):
        validate({"children": [row], "reason": reason}, decision.schema["parameters"])
    validate({"children": [row], "reason": "Used findings"}, decision.schema["parameters"])
