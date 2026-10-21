"""Explicit Resume of an answered tree: release its stop, select no child implicitly."""

import pathlib
import time
import uuid

from ouroboros.control_actor import control_actor, observed_control_stop
from ouroboros.utils import utc_now_iso
from ouroboros.work_stop import release_refusal


def resume_terminal_tree(task_id: str) -> dict | None:
    from ouroboros.owner_pause import FENCE_RELEASED, fence_closed, launch_lock, read_fence, set_fence_state
    from ouroboros.task_results import _TRULY_TERMINAL_STATUSES, load_task_result
    from supervisor import queue as q
    from supervisor.budget_resume import _late_phase_refusal
    from supervisor.events_budget import _root_resume_state, hold_root_resume_descendants
    from supervisor.owner_pause_control import complete_owner_pause_latch, warm_paused_member

    root = pathlib.Path(q.DRIVE_ROOT)
    try:
        row = load_task_result(root, task_id, strict=True) or {}
        fence = read_fence(root, task_id) if row else {}
    except Exception:
        return {"ok": False, "error": "pause_record_unreadable"}
    if row.get("status") not in _TRULY_TERMINAL_STATUSES:
        return None
    with q._queue_lock:
        children = [task for task in [*q.PENDING, *(m.get("task") or {} for m in q.RUNNING.values())]
                    if str(task.get("root_task_id") or "") == task_id and task.get("id") != task_id]
    if not children:
        return None  # the existing late-phase door still owns review-only work
    if not fence_closed(fence):
        if (fence.get("resume_grant") or {}).get("tree_only"):
            return {"ok": True, "task_id": task_id, "tree_only": True, "owner_pause_released": True}
        return None
    if refusal := release_refusal(observed_control_stop(root, row, budget=q.BUDGET_ROOT_FENCES,
                                                       owner=fence), control_actor()):
        return refusal
    if refusal := _late_phase_refusal(q, root, task_id, row, fence):
        return refusal
    with q._queue_lock:
        state = _root_resume_state(q, task_id, root)
        complete_owner_pause_latch(task_id, fence)
        grant = {"by": control_actor(), "grant_id": uuid.uuid4().hex, "granted_at": utc_now_iso(),
                 "granted_at_ts": time.time(), "authority": "explicit_resume", "selected_by": "owner",
                 "generation": int(fence.get("generation") or 0), "root_resume_basis": state["basis"],
                 "tree_only": True}
        try:
            with launch_lock(root, task_id, wait=False):
                if read_fence(root, task_id) != fence:
                    return {"ok": False, "error": "selection_authority_changed"}
                set_fence_state(root, task_id, fence_id=fence["fence_id"], state=FENCE_RELEASED,
                                expected_state=fence["state"], release_reason="owner_resume_tree", resume_grant=grant,
                                warm_members=[tid for tid, meta in q.RUNNING.items() if warm_paused_member(meta)
                                              and (meta.get("task") or {}).get("root_task_id") == task_id])
                latch = q.BUDGET_ROOT_FENCES.pop(task_id, None) or {}
                held, _markers, _rebound = hold_root_resume_descendants(q, task_id, latch, grant, actor_id=task_id)
                persisted = q.persist_queue_snapshot(reason="owner_pause_tree_resumed")
        except Exception as exc:
            return {"ok": False, "error": "grant_not_recorded", "detail": str(exc)[:200]}
    return {"ok": True, "task_id": task_id, "root_task_id": task_id, "tree_only": True,
            "owner_pause_released": True, "grant_id": grant["grant_id"], "held_siblings": held,
            "snapshot_persisted": bool(persisted)}
