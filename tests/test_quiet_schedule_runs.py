"""Quiet scheduled results stay internal through Project/Main completion delivery."""

import pytest

from ouroboros.projects_registry import bind_task_to_project, create_project
from ouroboros.task_results import load_task_result, write_task_result
from ouroboros.terminal_projection import SETTLEMENT_DEFERRED, SETTLEMENT_NONE, SETTLEMENT_SETTLED, settle_terminal_projection
from supervisor.event_observation import ObservedEventQueue
from tests._dialogue import chat_rows


@pytest.fixture
def scheduled_project(tmp_path):
    project = create_project(tmp_path, "checks", name="Checks")
    task = {
        "id": "scheduled-check", "type": "task", "title": "Check for changes",
        "text": "Check for changes", "chat_id": project["chat_id"], "project_id": project["id"],
        "root_task_id": "scheduled-check", "delegation_role": "root",
        "metadata": {"schedule_occurrence": {"schedule_id": "daily-check", "token": "occurrence-1"}},
    }
    bind_task_to_project(tmp_path, task["id"], project["id"], project["chat_id"],
                         origin={"absent": "system"})
    return task


@pytest.mark.parametrize("silent,notice", [(True, ""), (False, ""), (True, "A tool failed.")],
                         ids=["quiet", "ordinary", "quiet-with-notice"])
def test_project_completion_mirrors_only_published_results(tmp_path, scheduled_project, silent, notice):
    task = scheduled_project
    write_task_result(tmp_path, task["id"], "completed", **{k: v for k, v in task.items() if k != "id"},
                      result="The complete result.", terminal_origin="model_final", wake_silent=silent,
                      terminal_host_notice=notice, outcome_axes={"execution": {"status": "ok"}})
    bus = ObservedEventQueue()
    quiet = silent and not notice
    assert settle_terminal_projection(tmp_path, task["id"], task=task, event_queue=bus) == (
        SETTLEMENT_SETTLED if quiet else SETTLEMENT_DEFERRED)
    rows = chat_rows(tmp_path)
    summary = next(row for row in rows if row.get("type") == "task_summary")
    assert summary["chat_id"] == task["chat_id"]
    assert summary["wake_silent"] is silent and summary["quiet_effective"] is bool(quiet)
    if quiet:
        assert summary["text"] == "Done · no message"
        assert bus.empty()
        assert not any(row.get("type") == "project_completion_summary" for row in rows)
    else:
        mirror = bus.get_nowait()
        assert mirror["system_type"] == "project_completion_summary"
        assert mirror["chat_id"] == 1
        answer = mirror["progress_meta"].get("completion_answer")
        assert answer == (None if silent else "The complete result.")
        assert summary["text"] != "Done · no message"
    stored = load_task_result(tmp_path, task["id"], strict=True)
    assert stored["result"] == "The complete result."
    if quiet:
        assert stored["canonical_terminal_projection"]["main_disposition"] == "ineligible"
        assert stored["canonical_terminal_projection_ready"] is None
        assert settle_terminal_projection(tmp_path, task["id"], task=task, event_queue=bus) == SETTLEMENT_NONE
        assert len(chat_rows(tmp_path)) == len(rows) and bus.empty()
