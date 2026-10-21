"""The automatic reply crosses the same current place state and Safety boundary as speech."""
from __future__ import annotations

import hashlib
import json
from ouroboros.places import PlaceError, conversation_chat_id, get_place, resolve_place


def record_notice(root, *, place_id: str, conversation_key: str, task_id: str, text: str, identity: str,
                  transport: dict | None = None):
    from ouroboros import dialogue_store
    from ouroboros.utils import utc_now_iso
    row = {"ts": utc_now_iso(), "direction": "system", "chat_id": conversation_chat_id(conversation_key),
           "user_id": 0, "text": text, "source": "presence", "place_id": place_id, "task_id": task_id,
           "type": "place_notice", "client_message_id": "place-notice:" + identity,
           "transport": transport or {"conversation_key": conversation_key},
           "presence_provenance": {"binding_id": place_id, "conversation_key": conversation_key}}
    from ouroboros.presence_runner import _configured_gate
    gate = _configured_gate(root)
    key, lock = gate._conversation("notice:" + conversation_key)
    with lock, gate._file_lock(gate._conversation_file(key)):
        existing = dialogue_store.rows_by_client_id(root, row["client_message_id"], chat_id=row["chat_id"])
        if existing:
            return existing[0]
        return dialogue_store.append(root, "chat", row, feed=True)


def prepare_focus_reply(ctx, text: str, *, quiet: bool = False) -> tuple[bool, str]:
    metadata = getattr(ctx, "task_metadata", {}) or {}
    if metadata.get("wake_cause") != "focus":
        return True, ""
    from ouroboros.tool_access import canonical_data_root
    from ouroboros.presence_context import confirmed_delivery_receipts
    from ouroboros.presence_continuation import _handoff_ref, selection_for
    root = canonical_data_root(ctx)
    focus, presence = metadata["focus"], metadata["presence"]
    place_id = focus["place_id"]
    outcome = "silent" if quiet else "deferred" if _handoff_ref(ctx) else "tool_delivered" if confirmed_delivery_receipts(ctx) else "message"
    if outcome in {"message", "deferred"} and text:
        try:
            place = get_place(root, place_id)
            state, label = place.state, place.label
        except PlaceError as exc:
            if exc.code != "place_not_found":
                raise
            state, label = "disconnected", place_id
        subject = {"text": text, "destination": presence["event"]["destination"], "place_id": place_id}
        digest = hashlib.sha256(json.dumps(subject, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if state in {"silent", "paused", "disconnected"}:
            message = f"Reply held: {label} is {state.title()}"
            record_notice(root, place_id=place_id, conversation_key=focus["conversation_key"],
                          task_id=ctx.task_id, text=message, identity=f"{ctx.task_id}:{digest}:held")
            ctx._focus_reply_hold = message
            outcome = "silent"
        elif getattr(ctx, "_focus_checked_reply", None) != digest:
            from ouroboros.safety import check_safety
            allowed, message = check_safety("place_reply", subject, ctx=ctx)
            if not allowed:
                return False, message
            ctx._focus_checked_reply = digest
    old = getattr(ctx, "_presence_completion", {}) or {}
    selection = old.get("selection") if old.get("message") == text else None
    ctx._presence_completion = {"outcome": outcome, "message": text,
                                "selection": selection or selection_for(ctx, hashlib.sha256(text.encode()).hexdigest())}
    ctx._presence_completion_accepted = True
    return True, ""


def record_late_delivery(root, skill: str, payload: dict, client_id: str):
    """Receipts are evidence even when the destination is now closed to writes."""
    if payload["state"] not in {"accepted", "delivered"}:
        return
    place = resolve_place(root, connector=skill, provider=payload["provider"], account_id=payload["account_id"],
                          conversation_id=payload["conversation_id"], thread_id=payload["thread_id"])
    if place is None:
        from ouroboros.places import places_of_connector
        place = next((p for p in places_of_connector(root, skill) if p.destination and
                      all(p.destination.get(key, "") in (payload[source], "*") for key, source in
                          (("transport", "provider"), ("account_id", "account_id"),
                           ("conversation_id", "conversation_id"), ("thread_id", "thread_id")))), None)
    if place is None or place.state not in {"silent", "paused"}:
        return
    from ouroboros.presence_bindings import conversation_key
    key = conversation_key(*(payload[k] for k in ("provider", "account_id", "conversation_id", "thread_id")))
    record_notice(root, place_id=place.place_id, conversation_key=key, task_id="",
                  text=f"Delivery reported while {place.label} is {place.state.title()}: {payload['text']}",
                  identity=client_id + ":late", transport={"conversation_key": key, "receipt": payload})
