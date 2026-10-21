"""Read-only consciousness facts from places, current roots and durable results."""

from ouroboros.usage_origin import cause_label


def place_views(drive_root) -> list[dict]:
    """One row per configured place; unavailable room counts stay unknown."""
    from ouroboros import places

    views = []
    room_index = getattr(places, "place_room_index", None)
    for place in places.load_places(drive_root):
        view = dict(places.place_summary(place))
        try:
            rooms = room_index(drive_root, place.place_id) if room_index else None
        except Exception:
            rooms = None
        view["rooms"] = rooms
        if rooms is not None:
            counts = [room.get("unanswered_count") for room in rooms]
            view["unanswered"] = sum(counts) if all(isinstance(n, int) for n in counts) else None
        else:
            view.setdefault("unanswered", None)
        views.append(view)
    return views


def places_text(views) -> str:
    if views is None:
        return "unknown (place index unavailable)"
    lines = []
    for view in views:
        count = view.get("unanswered")
        addresses = [str(room.get("address") or f'chat_history(chat_id={int(room["room_chat_id"])})')
                     for room in view.get("rooms") or []]
        address = "; ".join(addresses) or ("no captured room" if view.get("rooms") == [] else "room address unknown")
        lines.append(f'{view.get("label") or view["place_id"]} [{view["place_id"]}]: {view["state"]}; '
                     f'unanswered: {count if count is not None else "unknown"}; {address}')
    return "\n  ".join(lines) if lines else "none"


def cause_views(rows, places) -> list[dict] | None:
    if rows is None:
        return None
    return [{**row, "label": cause_label(row["cause"], places or ())} for row in rows]


def root_views(roots, places) -> list[dict]:
    return [{**root, "cause": root["consciousness_cause"],
             "cause_label": cause_label(root["consciousness_cause"], places or ())} for root in roots]


def spend_text(rows) -> str:
    if rows is None:
        return "unknown"
    return "; ".join(f'{row["label"]}: {"at least " if row["unmetered_calls"] else ""}'
                     f'${row["usd"]:.2f} ({row["unmetered_calls"]} unmetered calls)' for row in rows) or "none"


def roots_text(rows) -> str:
    if rows is None:
        return "unknown"
    return "; ".join(f'{row["task_id"]}: {row["title"]} ({row["cause_label"]})' for row in rows) or "none"


def recent_wakes(drive_root, places) -> list[dict]:
    """Wake facts among the 50 newest task rows, with explicit snapshot coverage.

    The indexed timestamp selection bounds both reading and decoding. Missing
    timing/check evidence stays absent; no log scan or parallel history store.
    """
    from ouroboros.consciousness_authority import wake_cause
    from ouroboros.task_store import documents_by_ids, newest_ids

    ids = newest_ids(drive_root, limit=50)
    documents = documents_by_ids(drive_root, ids)
    rows = []
    for task_id in ids:
        row = documents[task_id]
        metadata = row.get("metadata") or {}
        cause = wake_cause(metadata)
        if not cause:
            continue
        focus = metadata.get("focus") or {}
        place_id = str(focus.get("place_id") or "")
        rows.append({"task_id": task_id, "cause": cause, "place_id": place_id,
                     "place_label": cause_label(f"place:{place_id}", places or ()) if place_id else "",
                     "started_at": row.get("started_at"), "first_reply_at": row.get("first_reply_at"),
                     "finished_at": row.get("finished_at"), "outcome": row.get("status", "unknown"),
                     "cost_usd": row.get("cost_usd"), "unmetered": bool(row.get("unknown_unmetered")),
                     "checks": row.get("safety_checks", []), "summary": str(row.get("result") or "")})
    return rows
