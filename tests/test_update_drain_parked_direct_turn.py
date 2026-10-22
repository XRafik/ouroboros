from __future__ import annotations

import json
import pathlib
import threading
import time

import pytest

from ouroboros import model_sleep, owner_pause, owner_wait
from ouroboros.gateway import control
from ouroboros.model_wait import TaskModelWait
from ouroboros.owner_mailbox import write_owner_message
from ouroboros.review_pause import live_detached_operations
from ouroboros.task_results import STATUS_RUNNING, load_task_result, write_task_result
from supervisor import git_ops, workers
from supervisor.active_activity import (
    DirectActivityRegistry,
    get_direct_activity_registry,
)
from supervisor.budget_resume import resume_warm_owner_pause_root
from supervisor.owner_pause_control import request_owner_pause
from tests._budget_pause_exact_helpers import _install_queue, _loop_ctx
from tests.test_direct_chat_turn_owner_control import _live_chat_agent


@pytest.fixture(autouse=True)
def _isolated_direct_registry_and_short_drain(monkeypatch: pytest.MonkeyPatch):
    get_direct_activity_registry().clear()
    workers.open_repo_writer_admission()
    orig_wait = DirectActivityRegistry.wait_until_empty
    monkeypatch.setattr(
        DirectActivityRegistry,
        "wait_until_empty",
        lambda self, timeout=0.05: orig_wait(self, min(float(timeout), 0.05)),
    )
    yield
    workers.open_repo_writer_admission()
    get_direct_activity_registry().clear()


def _direct_turn_setup(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    task_id: str,
):
    queue_mod, state_mod, workers_mod = _install_queue(tmp_path, monkeypatch)
    monkeypatch.setattr(state_mod, "budget_remaining", lambda *_a, **_k: 5.0)
    monkeypatch.setattr(git_ops, "DRIVE_ROOT", tmp_path)
    monkeypatch.setattr(workers_mod, "kill_workers_for_update", lambda **kwargs: [])
    write_task_result(
        tmp_path,
        task_id,
        STATUS_RUNNING,
        chat_id=0,
        _is_direct_chat=True,
        admitted_dispatch_attempt=1,
    )
    _live_chat_agent(monkeypatch, task_id=task_id)
    ctx, limit = _loop_ctx(tmp_path, task_id, direct=True)
    ctx.pending_events, ctx.current_chat_id = [], 0
    waiter = TaskModelWait(
        task={"id": task_id, "budget_drive_root": str(tmp_path)},
        drive_root=tmp_path,
        event_queue=None,
        worker_slot_held=False,
    )
    waiter.tool_context, ctx.model_wait_context = ctx, waiter
    ctx.owner_wait_callback = owner_wait.direct_owner_wait
    return queue_mod, ctx, limit


def _wait_for_owner_wait_state(
    drive_root: pathlib.Path,
    task_id: str,
    *,
    expected_reason: str,
    timeout: float = 5.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        wait = (load_task_result(drive_root, task_id) or {}).get("owner_wait") or {}
        if (
            wait.get("state") == "waiting"
            and wait.get("reason") == expected_reason
            and isinstance(wait.get("source_ref"), dict)
        ):
            return wait
        time.sleep(0.02)
    raise RuntimeError(
        f"direct turn {task_id} did not enter owner_wait(reason={expected_reason!r}) within {timeout}s"
    )


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#2191")
def test_update_quiesce_proceeds_when_warm_owner_paused_direct_turn_reviews_settled(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2191 negative reproduction: a direct turn parked warm in direct_owner_wait
    under owner_pause whose detached reviews have already settled and with no tool
    or model call in flight must not block _quiesce_repo_writers / _stop_repo_writers."""
    task_id = "390ae3e9"
    _queue, ctx, limit = _direct_turn_setup(tmp_path, monkeypatch, task_id)
    if request_owner_pause(task_id, request_id="press").get("state") != "requested":
        raise RuntimeError("owner pause fence was not requested")
    fence = owner_pause.read_fence(tmp_path, task_id)
    registry = get_direct_activity_registry()

    def _run_direct_turn() -> None:
        try:
            owner_wait.park_owner_pause_warm(
                limit,
                ctx,
                fence=fence,
                detached=[{"owner_id": "review-settled-1", "surface": "multi_model_review"}],
            )
        finally:
            registry.unregister(task_id)

    worker = threading.Thread(target=_run_direct_turn, daemon=True)
    worker.start()
    try:
        wait = _wait_for_owner_wait_state(tmp_path, task_id, expected_reason="owner_pause")
        if (
            wait.get("state") != "waiting"
            or wait.get("reason") != "owner_pause"
            or not isinstance(wait.get("source_ref"), dict)
            or live_detached_operations(task_id) != []
            or not worker.is_alive()
        ):
            raise RuntimeError("preconditions for settled warm owner-pause direct turn were not met")

        blockers = control._quiesce_repo_writers("smart")
        if blockers:
            if blockers != [f"active:{task_id}"]:
                raise RuntimeError(f"unexpected blocker payload: {blockers!r}")
            failure = control._fence_failure(blockers)
            payload = json.loads(failure.body.decode("utf-8"))
            if (
                failure.status_code != 409
                or payload.get("reason") != "update_writer_fence_blocked"
                or payload.get("blockers") != [f"active:{task_id}"]
                or payload.get("restart_required") is not False
            ):
                raise RuntimeError(f"unexpected fence failure response: {payload!r}")
        assert blockers == []
    finally:
        resume_warm_owner_pause_root(task_id)
        worker.join(timeout=5.0)
        if worker.is_alive():
            raise RuntimeError("warm-parked direct turn thread did not exit after resume_warm_owner_pause_root")


def test_update_quiesce_blocks_live_unparked_busy_direct_turn(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2191 control case: a live, unparked busy direct turn (no owner_wait) must
    continue to block _quiesce_repo_writers / _stop_repo_writers with 'active:<id>'."""
    task_id = "direct-busy-turn"
    _direct_turn_setup(tmp_path, monkeypatch, task_id)
    registry = get_direct_activity_registry()
    entered = threading.Event()
    release = threading.Event()

    def _run_busy_direct_turn() -> None:
        try:
            entered.set()
            release.wait(timeout=5.0)
        finally:
            registry.unregister(task_id)

    worker = threading.Thread(target=_run_busy_direct_turn, daemon=True)
    worker.start()
    try:
        assert entered.wait(timeout=2.0)
        assert (load_task_result(tmp_path, task_id) or {}).get("owner_wait") is None

        blockers = control._quiesce_repo_writers("smart")
        assert blockers == [f"active:{task_id}"]

        failure = control._fence_failure(blockers)
        assert failure.status_code == 409
        payload = json.loads(failure.body.decode("utf-8"))
        assert payload["reason"] == "update_writer_fence_blocked"
        assert payload["blockers"] == [f"active:{task_id}"]
        assert payload["restart_required"] is False
    finally:
        release.set()
        worker.join(timeout=5.0)
        assert not worker.is_alive()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#2191")
@pytest.mark.parametrize(
    ("task_id", "wait_reason"),
    [
        ("direct-quiz-wait", "owner"),
        ("direct-warm-sleep", "sleep"),
    ],
)
def test_update_quiesce_proceeds_for_direct_quiz_wait_and_warm_sleep(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    task_id: str,
    wait_reason: str,
) -> None:
    """#2191 item 2: a direct turn parked in direct_owner_wait via wait_after_tools
    for either escalate(wait_for_answer=True) (reason='owner') or warm model sleep
    await_messages(mode='warm') (reason='sleep') stays registered in
    DirectActivityRegistry and hits the same drain_repo_writers refusal."""
    _queue, ctx, limit = _direct_turn_setup(tmp_path, monkeypatch, task_id)
    if wait_reason == "owner":
        ctx._owner_wait_requested = "quiz-direct-1"
    else:
        armed = model_sleep.request_sleep(
            ctx,
            model_sleep.selectors(ctx, wake_after_sec=60),
            model_sleep.MODE_WARM,
        )
        if armed.get("reason") != "sleep_armed":
            raise RuntimeError(f"warm model sleep was not armed: {armed!r}")
    registry = get_direct_activity_registry()

    def _run_direct_wait() -> None:
        try:
            owner_wait.wait_after_tools(
                ctx,
                limit.messages,
                limit.llm_trace,
                limit.accumulated_usage,
                limit.round_idx,
                limit.tool_schemas,
                limit.owner_msg_seen,
            )
        finally:
            registry.unregister(task_id)

    worker = threading.Thread(target=_run_direct_wait, daemon=True)
    worker.start()
    try:
        wait = _wait_for_owner_wait_state(tmp_path, task_id, expected_reason=wait_reason)
        if (
            wait.get("state") != "waiting"
            or wait.get("reason") != wait_reason
            or not isinstance(wait.get("source_ref"), dict)
            or not worker.is_alive()
        ):
            raise RuntimeError(f"preconditions for direct {wait_reason} wait were not met")

        blockers = control._quiesce_repo_writers("smart")
        if blockers:
            if blockers != [f"active:{task_id}"]:
                raise RuntimeError(f"unexpected blocker payload: {blockers!r}")
        assert blockers == []
    finally:
        write_owner_message(
            tmp_path,
            "wake from test cleanup",
            task_id=task_id,
            msg_id=f"wake-{task_id}",
        )
        worker.join(timeout=5.0)
        if worker.is_alive():
            raise RuntimeError(f"direct {wait_reason} wait thread did not exit after owner message")
