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

# Legacy typed names remain readable; release policy consumers move here next.
STOP_REASONS = {
    "saved_work_hold": {"cause": "app_stop", "release": "resume", "ui_code": "saved_work_hold"},
    "owner_restart_hold": {"cause": "app_stop", "release": "resume", "ui_code": "owner_restart_hold"},
    "panic_hold": {"cause": "panic", "release": "owner", "ui_code": "panic_hold"},
    "saved_sleep_recovery": {"cause": "app_stop", "release": "resume", "ui_code": "saved_sleep_recovery"},
    "unsaved_pause_intent": {"cause": "pause", "release": "resume", "ui_code": "unsaved_pause_intent"},
    "root_fence_lifted_pending_selection": {
        "cause": "awaiting_selection", "release": "resume", "ui_code": "root_fence_lifted_pending_selection"},
    "root_fence_member_pending_selection": {
        "cause": "awaiting_selection", "release": "resume", "ui_code": "root_fence_member_pending_selection"},
    "continuation_writer_unsettled": {"cause": "wait", "release": "none", "ui_code": "continuation_writer_unsettled"},
    "owner": {"cause": "pause", "release": "resume", "ui_code": "owner_paused"},
    "budget": {"cause": "money", "release": "resume", "ui_code": "budget_paused"},
    "authority": {"cause": "authority", "release": "resume", "ui_code": "budget_paused"},
    "sleep": {"cause": "wait", "release": "none", "ui_code": "sleeping"},
}
REFUSAL_REASONS = frozenset({
    "root_acceptance_fenced_at_restore", "pause_record_unreadable_at_revoke",
    "dispatch_outcome_unknown", "continuation_publication_unconfirmed", "_owner_hold",
})


def reason_policy(reason: str) -> dict:
    """Classify the existing vocabulary; an unknown name stays an unknown refusal."""
    if reason in STOP_REASONS:
        return dict(STOP_REASONS[reason])
    if (reason in REFUSAL_REASONS or reason.startswith(("restore_refused:", "malformed_", "stale_"))
            or reason.endswith("_unwritten")):
        return {"cause": "refusal", "release": "resume", "ui_code": "restore_refused"}
    return {"cause": "refusal", "release": "none", "ui_code": "restore_refused"}


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
