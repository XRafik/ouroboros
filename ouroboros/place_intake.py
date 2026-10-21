"""Model-free attention decisions after the room has durably heard an event."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from ouroboros import presence_admission
from ouroboros.places import FACT_LEGACY_ADDRESSED, PlaceError, get_place, wake_matches


def decide_attention(root: Path, admission, event) -> tuple[str, dict]:
    """Return silent / retry / focus, consulting current owner choices each time."""
    try:
        place = get_place(root, admission.place.place_id)
    except PlaceError as exc:
        if exc.code != "place_not_found":
            raise
        return "silent", {}
    facts = event.facts if event.facts is not None else (FACT_LEGACY_ADDRESSED,)
    if event.actor.get("is_bot") is True:
        facts = (*facts, "from_bot")
    if place.state == "paused" or not presence_admission.focus_enabled(root) or not wake_matches(place, facts):
        return "silent", {}
    allowance = presence_admission.focus_allowance(root)
    if allowance.get("status") != "available":
        retry_after = 60  # transport backoff when there is no known allowance reset
        try:
            reset = datetime.fromisoformat(str(allowance.get("resets_at") or "").replace("Z", "+00:00"))
            retry_after = max(1, int((reset - datetime.now(timezone.utc)).total_seconds()))
        except (ValueError, TypeError):
            pass
        return "retry", {**allowance, "retry_after": retry_after}
    return "focus", allowance


def settle_heard(root: Path, task: dict, event):
    """A successful silent intake is final for this event, including after a later switch On."""
    from ouroboros.presence_runner import presence_result_from_stored
    from ouroboros.task_results import load_task_result, write_task_result
    metadata = {**task["metadata"], "presence_outcome": "silent", "presence_result_text": "",
                "focus_heard_only": True}
    write_task_result(root, task["id"], "completed", create_only=True, strict_existing_dict=True,
                      metadata=metadata, chat_id=task["chat_id"], _is_direct_chat=True,
                      source=task["source"], result="", terminal_origin="host_notice")
    row = load_task_result(root, task["id"], strict=True)
    if row.get("status") not in {"completed", "failed"}:
        return None  # another request already admitted it; the Host joins its custody
    return replace(presence_result_from_stored(row, task["id"]), continuation_version=event.continuation_version)


def offer_to_author(root, task: dict, event) -> bool:
    """A current author hears a new event as context, without another focus generation."""
    from ouroboros.conversation_lease import live_author
    from ouroboros.owner_mailbox import write_task_message
    author = live_author(event.conversation_key, drive_root=root)
    if not author or author == task["id"]:
        return False
    import json
    text = json.dumps({"actor": dict(event.actor), "event": event.text,
                       "source_event_id": event.source_event_id, "conversation_key": event.conversation_key,
                       **{key: task[key] for key in ("attachment_manifest", "attachment_manifest_ref") if key in task}}, ensure_ascii=False)
    if not write_task_message(root, text, author, source_task_id=task["id"], provenance="place_event",
                              msg_id="place-event:" + task["metadata"]["presence_event_identity"],
                              sender_origin={"place_id": task["metadata"]["focus"]["place_id"],
                                             "conversation_key": event.conversation_key}):
        raise OSError("The current author could not retain this place arrival; retry.")
    return True
