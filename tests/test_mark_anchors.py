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
