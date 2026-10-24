"""A mark tied to an action meets the mind in that action's result, once per task.

The anchor is the mind's own choice; the host compares it literally with the call
and adds the mark's words as a host note. A call it does not name, a released mark,
another room's mark and a second call in the same task get nothing.
"""
from __future__ import annotations

import json
import pathlib

from ouroboros.chronicle_store import ChronicleStore
from ouroboros.mark_anchors import anchor_problem, deliver_anchored_marks, matches
from ouroboros.memory_view import _marks_text
from ouroboros.tools.chronicle import _chronicle_write, _memory_mark, _memory_read
from ouroboros.tools.registry import ToolContext
from ouroboros.tools.tool_result import ToolResult


def ctx_for(root: pathlib.Path, task_id: str = "root0001", chat_id: int = 1) -> ToolContext:
    return ToolContext(repo_dir=root, drive_root=root, task_id=task_id, current_chat_id=chat_id)


def mark(ctx, text, anchor, **fields):
    note = json.loads(_chronicle_write(ctx, kind="note", text="a lesson worth keeping"))
    return json.loads(_memory_mark(ctx, text=text, node_id=note["node_id"], anchor=anchor, **fields))


def run(ctx, tool, args, text="output"):
    return deliver_anchored_marks(ctx, tool, args, ToolResult(status="ok", code="OK", text=text))


def test_anchors_match_tools_with_text_and_paths_literally():
    assert matches({"tool": "run_command"}, "run_command", {"cmd": ["ls"]})
    assert matches({"tool": "run_command", "text": "pytest"}, "run_command", {"cmd": ["python", "-m", "pytest", "-q"]})
    assert not matches({"tool": "run_command", "text": "pytest"}, "run_command", {"cmd": ["ls", "-la"]})
    assert not matches({"tool": "run_command"}, "read_file", {"path": "x"})
    for path in ("web/modules/chat.js", "/repo/web/modules/chat.js", "./web/modules/chat.js"):
        assert matches({"path": "web/modules/chat.js"}, "edit_text", {"path": path})
    assert matches({"path": "web/modules/"}, "write_file", {"path": "/repo/web/modules/settings.js"})
    assert not matches({"path": "web/modules/chat.js"}, "edit_text", {"path": "web/modules/chat.jsx"})
    assert not matches({"path": "web/modules"}, "edit_text", {"path": "web/modules_old/a.js"})
    # A path inside file text or a sentence is not a call naming that path; a command's words match as typed.
    assert not matches({"path": "docs/"}, "write_file", {"path": "notes/a.md", "content": "see docs/ARCHITECTURE.md\nmore"})
    assert not matches({"path": "web/modules"}, "edit_text",
                       {"path": "tests/test_foo.py", "old_str": 'import x from "/repo/web/modules/settings.js"'})
    assert matches({"path": "docs/"}, "run_command", {"cmd": ["wc", "-l", "docs/CHECKLISTS.md"]})
    assert matches({"tool": "run_command", "text": "pytest -q"}, "run_command", {"cmd": ["python", "-m", "pytest", "-q"]})
    assert matches({"tool": "run_command", "text": 'echo "hi"'}, "run_command", {"cmd": 'echo "hi"'})
    assert anchor_problem({"tool": "run_command", "text": "pytest"}) == ""
    assert anchor_problem({"path": "a/b"}) == ""
    for bad in ({}, {"text": "x"}, {"tool": ""}, {"tool": "a", "path": "b"}, {"path": ""}, "run_command"):
        assert anchor_problem(bad)


def test_an_anchored_mark_meets_its_action_once_per_task(tmp_path):
    ctx = ctx_for(tmp_path)
    made = mark(ctx, "A quiet pytest tail hides failures: read the exit code.", {"tool": "run_command", "text": "pytest"})
    assert made["ok"], made
    unrelated = run(ctx, "run_command", {"cmd": ["ls"]})
    assert unrelated.text == "output" and unrelated.host_annotations == ()
    first = run(ctx, "run_command", {"cmd": ["python", "-m", "pytest", "-q"]}, text="3 passed")
    assert first.text.startswith("3 passed\n\n")
    assert "A quiet pytest tail hides failures" in first.text and "run_command with 'pytest'" in first.text
    assert first.producer_text == "3 passed" and len(first.host_annotations) == 1
    again = run(ctx, "run_command", {"cmd": ["python", "-m", "pytest"]}, text="1 failed")
    assert again.text == "1 failed"
    # A new task meets it again.
    assert "A quiet pytest tail" in run(ctx_for(tmp_path, task_id="root0002"), "run_command", {"cmd": ["pytest"]}).text


def test_released_and_foreign_room_marks_stay_silent_and_a_new_mark_acts_next_call(tmp_path):
    ctx = ctx_for(tmp_path)
    foreign = mark(ctx_for(tmp_path, task_id="other001", chat_id=2), "Only for room two.", {"path": "docs/"})
    glob = mark(ctx, "Global: docs are English.", {"path": "docs/"}, scope="global")
    assert foreign["ok"] and glob["ok"]
    seen = run(ctx, "read_file", {"path": "docs/ARCHITECTURE.md"}).text
    assert "Global: docs are English." in seen and "Only for room two." not in seen
    released = json.loads(_memory_mark(ctx, release_id=glob["mark_id"], reason="no longer holds"))
    assert released["ok"], released
    later = ctx_for(tmp_path, task_id="root0003")
    assert run(later, "read_file", {"path": "docs/ARCHITECTURE.md"}).text == "output"
    # A mark written in this task acts from the next call.
    run(later, "memory_mark", {"text": "x"})
    mark(later, "Read the whole file before editing it.", {"tool": "edit_text"})
    run(later, "memory_mark", {"text": "x"})
    assert "Read the whole file before editing it." in run(later, "edit_text", {"path": "a.py"}).text


def test_a_malformed_anchor_is_refused_and_the_view_names_the_action(tmp_path):
    ctx = ctx_for(tmp_path)
    note = json.loads(_chronicle_write(ctx, kind="note", text="n"))
    refused = _memory_mark(ctx, text="x", node_id=note["node_id"], anchor={"tool": "run_command", "path": "a"})
    assert "TOOL_ARG_ERROR" in refused
    stored = ChronicleStore(tmp_path).publish([{"kind": "mark", "room_id": "1", "scope": "room", "text": "x",
                                                "author": {"kind": "helper"}, "anchor": {"path": ""},
                                                "target_ref": {"kind": "task", "task_id": "t"}}])
    assert stored.ok is False
    assert mark(ctx, "Check the exit code.", {"tool": "run_command", "text": "pytest"})["ok"]
    active = ChronicleStore(tmp_path).active_marks("1")
    assert active[-1]["anchor"] == {"tool": "run_command", "text": "pytest"}
    assert "meets me at run_command with 'pytest'" in _memory_read(ctx, room_id="1")
    shown = _marks_text([{"id": "m1", "scope": "room", "room": "Main", "text": "Check the exit code.", "by": "root",
                          "date": "2026-10-23", "target": "a note", "quote": "", "anchor": "run_command with 'pytest'"},
                         {"id": "m2", "scope": "global", "room": "Main", "text": "Plain.", "by": "root",
                          "date": "2026-10-23", "target": "a note", "quote": "", "anchor": ""}])
    assert "meets me at run_command with 'pytest'" in shown and shown.count("meets me at") == 1


def test_the_loop_delivers_an_anchored_mark_through_the_real_tool_execution(tmp_path, monkeypatch):
    """The seam the mind meets: ``_execute_single_tool`` composes the mark as a host note
    over the producer's own text, once per task, and leaves a call it does not name alone."""
    import ouroboros.safety as safety
    from ouroboros.loop_tool_execution import _execute_single_tool
    from ouroboros.tools.registry import ToolEntry, ToolRegistry

    monkeypatch.setattr(safety, "check_safety", lambda *_args, **_kwargs: (True, ""))
    ctx = ctx_for(tmp_path)
    assert mark(ctx, "Probe output is partial: read the receipt.", {"tool": "fixture_probe"})["ok"]
    registry = ToolRegistry(repo_dir=tmp_path, drive_root=tmp_path)
    registry.set_context(ctx)
    for name in ("fixture_probe", "fixture_other"):
        registry.register(ToolEntry(name, {"name": name, "description": "fixture",
                                           "parameters": {"type": "object", "properties": {}, "required": []}},
                                    lambda _ctx, _name=name: f"{_name} output"))
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)

    def call(name, call_id):
        return _execute_single_tool(registry, {"id": call_id, "function": {"name": name, "arguments": "{}"}}, logs)

    other = call("fixture_other", "c0")
    assert other["result"] == "fixture_other output"
    first = call("fixture_probe", "c1")
    assert first["result"].startswith("fixture_probe output\n\n")
    assert "Probe output is partial: read the receipt." in first["result"] and first["is_error"] is False
    assert first["tool_result"].producer_text == "fixture_probe output"
    assert call("fixture_probe", "c2")["result"] == "fixture_probe output"


def test_a_task_moved_to_another_project_meets_that_room_s_marks(tmp_path, monkeypatch):
    """The cache follows the task's project placement: a move changes the room whose marks act."""
    import ouroboros.dialogue_evidence as evidence
    import ouroboros.project_facts as facts

    main, beta = ctx_for(tmp_path), ctx_for(tmp_path, task_id="beta0001", chat_id=7)
    assert mark(main, "MAIN_ONLY_LESSON", {"tool": "edit_text"})["ok"]
    assert mark(beta, "BETA_ONLY_LESSON", {"tool": "edit_text"})["ok"]
    worker = ctx_for(tmp_path, task_id="mover001")
    run(worker, "read_file", {"path": "a"})  # fills the cache while the task is in Main
    monkeypatch.setattr(facts, "placed_project_id", lambda _ctx: "beta")
    monkeypatch.setattr(evidence, "own_room_chat", lambda _ctx, _root: 7)
    seen = run(worker, "edit_text", {"path": "a.py"}).text
    assert "BETA_ONLY_LESSON" in seen and "MAIN_ONLY_LESSON" not in seen


def test_an_anchored_publication_keeps_its_receipt_and_its_pass(tmp_path, monkeypatch):
    """A mark on submit_skill_to_hub trails the publication JSON behind the host-note boundary, so
    the receipt the publication veto reads is still recovered and a real PR keeps its pass."""
    from types import SimpleNamespace

    from ouroboros import loop_tool_execution as execution
    from ouroboros.skill_publish_result import (
        SKILL_PUBLISH_TARGET_METADATA_KEY, apply_skill_publish_receipt_veto, serialize_skill_publish_result)
    from ouroboros.tools.tool_result import _HOST_NOTE_SEPARATOR

    snapshot, ruleset, repo = "a" * 64, "b" * 64, "OuroborosHub/OuroborosHub"
    payload = serialize_skill_publish_result(
        ok=True, status="pr_opened", reason_code="", skill="demo", snapshot_hash=snapshot,
        scanner={"engine": "betterleaks", "version": "1.8.1", "ruleset_sha256": ruleset}, completed_stage="pr_opened",
        completed_effects=[{"stage": "branch_created", "kind": "branch", "branch": "submit/demo-v1"},
                           {"stage": "commit_created", "kind": "commit", "commit_sha": "c" * 40},
                           {"stage": "pr_opened", "kind": "pull_request"}],
        receipt={"kind": "github_pull_request", "repository": repo, "url": f"https://github.com/{repo}/pull/17",
                 "number": 17, "skill": "demo", "snapshot_hash": snapshot, "ruleset_sha256": ruleset},
        expected_repository=repo)
    ctx = ctx_for(tmp_path, task_id="publish01")
    assert mark(ctx, "Check the license field before publishing.", {"tool": "submit_skill_to_hub"}, scope="global")["ok"]
    registry = SimpleNamespace(_ctx=ctx, CODE_TOOLS=frozenset(),
                               execute_result=lambda *_a: ToolResult(status="ok", code="OK", text=payload))
    monkeypatch.setattr(execution, "persist_call", lambda *a, **k: {})
    (tmp_path / "logs").mkdir(exist_ok=True)
    row = execution._execute_single_tool(registry, {"id": "c1", "function": {
        "name": "submit_skill_to_hub", "arguments": json.dumps({"skill": "demo"})}}, tmp_path / "logs", ctx.task_id)
    assert "Check the license field before publishing." in row["result"]
    assert row["result"].partition(_HOST_NOTE_SEPARATOR)[0] == payload
    assert "skill_publish_receipt" in row["result_meta"]
    task = {"type": "skill_publish", "metadata": {SKILL_PUBLISH_TARGET_METADATA_KEY: {"skill": "demo", "repository": repo}}}
    outcome = {"outcome_axes": {"execution": {"status": "ok", "reason_code": "final_message"},
                                "objective": {"status": "pass", "source": "result_review"}}}
    apply_skill_publish_receipt_veto(outcome, task, {"tool_calls": [{"tool": "submit_skill_to_hub", **row["result_meta"]}]})
    assert outcome["outcome_axes"]["objective"]["status"] == "pass"
