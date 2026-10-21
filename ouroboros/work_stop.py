"""Current stops and cause-free Q9 selections: pure record construction.

The queue owns publication; exact grants keep their existing single-use CAS.
A selection survives consumption, but carries no reason from the released stop.
Technical refusals and writer waits are classified separately from decisions.
"""

SELECTION_KEY = "_resume_selection"
SELECTION_BINDING = (
    "root_task_id", "root_resume_basis", "root_grant_id", "root_resume_generation",
    "fence_id", "root_fence_id", "grant_id", "grant_generation",
)

# The only translation from transport names to lifecycle policy.
STOP_REASONS = {
    "saved_work_hold": {"cause": "app_stop", "release": "resume", "ui_code": "saved_work_hold"},
    "owner_restart_hold": {"cause": "app_stop", "release": "resume", "ui_code": "owner_restart_hold", "door": "owner_restart"},
    "panic_hold": {"cause": "panic", "release": "owner", "ui_code": "panic_hold"},
    "saved_sleep_recovery": {"cause": "app_stop", "release": "resume", "ui_code": "saved_sleep_recovery",
                             "door_replaceable": True, "replaces_door": False},
    "unsaved_pause_intent": {"cause": "pause", "release": "resume", "ui_code": "owner_paused", "needs_source": True},
    "root_fence_lifted_pending_selection": {
        "cause": "awaiting_selection", "release": "resume", "ui_code": "root_fence_lifted_pending_selection"},
    "root_fence_member_pending_selection": {
        "cause": "awaiting_selection", "release": "resume", "ui_code": "root_fence_member_pending_selection"},
    "continuation_writer_unsettled": {"cause": "wait", "release": "none", "ui_code": "continuation_writer_unsettled",
                                      "wait_for": "continuation_writers", "door_replaceable": True},
    "owner": {"cause": "pause", "release": "resume", "ui_code": "owner_paused"},
    "budget": {"cause": "money", "release": "resume", "ui_code": "budget_paused"},
    "authority": {"cause": "authority", "release": "resume", "ui_code": "budget_paused"},
    "sleep": {"cause": "wait", "release": "none", "ui_code": "sleeping"},
}
REFUSAL_FACTS = {
    "stale_queue_row_grant_consumed": {"grant_state": "consumed"},
    "stale_resume_grant_superseded": {"grant_state": "superseded"},
    "dispatch_outcome_unknown": {"dispatch_unknown": True},
}


def reason_policy(reason: str) -> dict:
    """Classify the existing vocabulary; an unknown name stays an unknown refusal."""
    if reason in STOP_REASONS:
        return dict(STOP_REASONS[reason])
    return {"cause": "refusal", "release": "resume", "ui_code": "restore_refused",
            **REFUSAL_FACTS.get(reason, {})}


def record_policy(record: dict | None) -> dict:
    record = record or {}
    policy = reason_policy(str(record.get("reason") or ""))
    if policy["cause"] != "refusal":
        policy["release"] = record.get("release", policy["release"])
    return policy


def hold_fact(task: dict | None) -> dict | None:
    """Current explicit stop or owned writer wait; never a technical refusal."""
    hold = task.get("_budget_pause_hold") if isinstance(task, dict) else None
    return hold if isinstance(hold, dict) and record_policy(hold)["cause"] != "refusal" else None


def pause_marker(task: dict) -> dict:
    """A point's refusal alone is not evidence that its execution parked."""
    point = task.get("_budget_pause")
    return {key: value for key, value in point.items() if key != "refusal"} if isinstance(point, dict) else {}


def current_stop(task: dict | None, fences: dict | None = None) -> dict:
    """Pure projection: installation, tree, member. Waiting is not a stop.

    ``fences`` contains an observed ``owner`` fence and the ``budget`` root map.
    No reads, clock decisions or copied causes. A tree overlay retains the
    member's independent release rule; releasing the tree cannot waive it.
    """
    task, fences = task if isinstance(task, dict) else {}, fences or {}
    hold = hold_fact(task)
    member = {**hold, **record_policy(hold), "scope": "member"} if hold else {}
    if member.get("cause") == "wait":
        member = {}
    if not member:
        pause = pause_marker(task)
        policy = reason_policy(str(pause.get("reason") or (
            "owner" if pause.get("cause") == "owner_pause" else
            "budget" if pause.get("exact_continuation") or pause.get("status") == "paused_before_dispatch" else "")))
        if policy["cause"] not in {"wait", "refusal"}:
            if policy["cause"] == "pause":
                policy = reason_policy("root_fence_member_pending_selection")
            member = {**pause, **policy, "scope": "member"}
    owner = fences.get("owner") or {}
    root_id = str(task.get("root_task_id") or task.get("id") or "")
    budget = (fences.get("budget") or {}).get(root_id) or {}
    tree = {}
    if owner.get("state") in {"requested", "paused"}:
        tree = {**owner, **reason_policy("owner"), "scope": "tree"}
    elif budget.get("status") in {"active", "paused"}:
        from ouroboros.budget_pause import budget_fence_selected

        if not budget_fence_selected(task, budget):
            tree = {**budget, **reason_policy("owner" if budget.get("cause") == "owner_pause" else "budget"),
                    "scope": "tree"}
    if tree.get("cause") == "pause" and not hold and member.get("cause") == "awaiting_selection":
        member = {}  # its owner marker is this tree stop, not a second decision
    stop = {**tree, **({"member_stop": member} if member else {})} if tree else member
    installation = fences.get("installation")
    if installation:
        return {**installation, **({"member_stop": stop} if stop else {}), "scope": "installation"}
    return stop


def release_refusal(stop: dict | None, actor: dict | None) -> dict | None:
    """Permission to release, independent of proof that a continuation can run."""
    stop, actor = stop or {}, actor or {}
    if stop.get("release") == "owner" and actor.get("actor", "owner") != "owner":
        return {"ok": False, "error": "panic_requires_owner_resume"}
    if stop.get("release") == "none":
        return {"ok": False, "error": "stop_not_resumable"}
    return release_refusal(stop["member_stop"], actor) if stop.get("member_stop") else None


def door_can_replace(task: dict, reason: str) -> bool:
    """The existing door matrix: only sleep recovery / writer waits are weak.

    Sleep recovery itself replaces nothing. Exact money/owner pauses keep their
    own rule; a sleep marker is a wait and can acquire the door's stop.
    """
    prior = hold_fact(task)
    if prior:
        return bool(record_policy(prior).get("door_replaceable")
                    and reason_policy(reason).get("replaces_door", True))
    return not current_stop(task)


def writer_wait(task: dict | None) -> bool:
    return record_policy(hold_fact(task)).get("wait_for") == "continuation_writers"


_POINTS = ("_budget_pause", "_owner_wait_resume", "_working_recovery", "_budget_pause_resume", SELECTION_KEY)


def continuation_refusal(task: dict | None) -> dict:
    """Read a point's refusal, including the old shape until boot normalization."""
    task = task if isinstance(task, dict) else {}
    for key in _POINTS:
        point = task.get(key)
        if isinstance(point, dict) and isinstance(point.get("refusal"), dict):
            return point["refusal"]
    hold = task.get("_budget_pause_hold")
    if isinstance(hold, dict) and record_policy(hold)["cause"] == "refusal":
        return {**hold, **record_policy(hold)}
    if task.get("_continuation_prepared"):
        return {"reason": "continuation_publication_unconfirmed"}
    if task.get("_owner_hold"):
        return {"reason": "_owner_hold"}
    return {}


def clear_refusal(task: dict) -> None:
    for key in _POINTS:
        point = task.get(key)
        if isinstance(point, dict) and "refusal" in point:
            task[key] = {k: v for k, v in point.items() if k != "refusal"}
            if not task[key]:
                task.pop(key)
    if isinstance(task.get("_budget_pause_hold"), dict) and hold_fact(task) is None:
        task.pop("_budget_pause_hold")


def selection_record(task: dict) -> dict:
    """Selection can release a hold, repair a point, or select an orphaned owner marker."""
    record = hold_fact(task) or continuation_refusal(task)
    if record:
        return record
    stop = current_stop(task)
    return stop if stop.get("cause") == "awaiting_selection" else {}


def refuse_continuation(task: dict, record: dict) -> dict:
    """Retain the refusal on existing custody, preserving any current decision.

    With no surviving source, the pause locator carries only the refusal's
    identities. That is not an exact pause and cannot re-arm a spent grant.
    """
    refusal = {**record, **REFUSAL_FACTS.get(record["reason"], {})}
    refusal.pop("release", None)
    for key in _POINTS[:3]:
        if isinstance(task.get(key), dict):
            task[key] = {**task[key], "refusal": refusal}
            break
    else:
        key = SELECTION_KEY if isinstance(task.get(SELECTION_KEY), dict) else "_budget_pause"
        task[key] = {**(task.get(key) or {}), "refusal": refusal}
    task.pop("_budget_pause_resume", None)  # the refused grant is not executable
    return refusal


def declare_stop(task: dict, record: dict) -> dict:
    """Write a decision or a point refusal; only the door matrix replaces a stop.

    Explicit Pause releases its authorized prior decision under the queue lock.
    Other producers cannot silently erase it while publishing custody facts.
    """
    policy = record_policy(record)
    if policy["cause"] == "refusal":
        return refuse_continuation(task, record)
    prior = hold_fact(task)
    door = policy["cause"] in {"app_stop", "panic"}
    if door and not door_can_replace(task, record["reason"]) or prior and not door:
        return prior or current_stop(task)
    task.pop("_budget_pause_resume", None)
    task.pop(SELECTION_KEY, None)
    task["_budget_pause_hold"] = record
    return record


def stop_record(reason: str, *, held_at: str, detail: str = "", by: dict | None = None,
                binding: dict | None = None) -> dict:
    """Build the current hold without conflating its name and the actor's text."""
    return {**(binding or {}), "reason": reason, "release": reason_policy(reason)["release"],
            "by": dict(by) if by else {"actor": "host", "task_id": "", "text": "", "at": held_at},
            "held_at": held_at, "detail": str(detail or "")[:300]}


def resume_selection(binding: dict, *, selected_by: str, selected_at: str, by: dict) -> dict:
    """Copy identities only. ``selected_by`` is the Q9 door, ``by`` its attribution."""
    return {**{key: binding[key] for key in SELECTION_BINDING if key in binding},
            "selected_by": selected_by, "selected_at": selected_at, "by": dict(by)}


def retain_consumed_selection(task: dict, pause_row: dict) -> bool:
    """Retire a matching spent handoff, keeping the root's selection, never its stop.

    Local lineage alone decides whether this row can lend: reciprocal retry
    authority is still read by dispatch. A member's spent handoff creates no
    replacement dispatch carrier. A current hold is never replaced.
    """
    from ouroboros.task_results import resolve_task_lineage

    handoff = task.get("_budget_pause_resume") if isinstance(task.get("_budget_pause_resume"), dict) else {}
    grant = pause_row.get("grant") if isinstance(pause_row.get("grant"), dict) else {}
    if not (handoff.get("authority") == "explicit_resume" and grant.get("authority") == "explicit_resume"
            and pause_row.get("state") == "resumed" and grant.get("consumed_at")
            and not grant.get("revoked_at") and grant.get("grant_id")
            and handoff.get("grant_id") == grant["grant_id"]
            and handoff.get("pause_id") == pause_row.get("pause_id")
            and handoff.get("source_ref") == pause_row.get("source_ref")
            and handoff.get("grant_generation") == grant.get("generation")
            and not isinstance(task.get("_budget_pause_hold"), dict)):
        return False
    lineage = resolve_task_lineage(task.get("id"), **{key: task.get(key) for key in (
        "metadata", "root_task_id", "parent_task_id", "delegation_role", "original_task_id", "timeout_retry_from")})
    if lineage["parent_task_id"] and lineage["root_task_id"] != lineage["task_id"]:
        task.pop(SELECTION_KEY, None)
        return False
    task[SELECTION_KEY] = resume_selection(
        {**grant, "root_task_id": str(task.get("root_task_id") or task.get("id") or ""),
         "grant_generation": int(grant["generation"]), "fence_id": str(grant.get("root_fence_id") or "")},
        selected_by=str(grant.get("selected_by") or "owner"),
        selected_at=str(grant.get("granted_at") or ""), by=grant.get("by") or {})
    return True
