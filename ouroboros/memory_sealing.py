"""Own-work candidate selection and terminal links; neither invents page coverage."""
from __future__ import annotations

from ouroboros import chat_chain, memory_inventory


def failed_work_units(root, store):
    from ouroboros.task_results import list_task_results
    from ouroboros.memory_fallback import FallbackUnit
    from ouroboros.memory_inventory import OpenSegment

    failed = {str(row.get("task_id") or row.get("id")): row for row in list_task_results(
        root, statuses=["failed", "cancelled"], strict=True)}
    if not failed:
        return []
    pages = store.records(kinds=["page"])
    sealed_by_mind = {str(record.get("author", {}).get("task_id") or "") for record in pages
                      if record.get("author", {}).get("kind") == "mind"}
    pending = {}
    for record in store.pending_candidates():
        pending.setdefault(record["room_id"], set()).update(record["covers"]["rows"])
    units = []
    for room, entries in memory_inventory.open_rows_by_room(root).items():
        by_task = {}
        for entry in entries:
            task_id = str(entry[1].get("task_id") or "")
            if task_id in failed and task_id not in sealed_by_mind and entry[0]["row_sha256"] not in pending.get(room, ()):
                by_task.setdefault(task_id, []).append(entry)
        for task_id, rows in by_task.items():
            segment = OpenSegment(room, rows[0][0], rows[-1][0], tuple(rows), store.room_head(room))
            units.append(FallbackUnit("page", room, f"candidate:{task_id}:{rows[0][0]['row_sha256'][:12]}",
                                      segment=segment, candidate_task=task_id))
    return sorted(units, key=lambda unit: unit.segment.rows[0][2])


def terminal_links(root, record, cache=None):
    """Only this page writer's later typed terminal rows, as separately attributed addresses."""
    author, metadata = record.get("author", {}), record.get("metadata", {})
    task_id = str(author.get("task_id") or "")
    if record.get("kind") != "page" or author.get("kind") != "mind" or not task_id:
        return []
    end = int(metadata.get("terminal_after_pos", (record.get("covers", {}).get("stream_span") or [0, 0])[-1]))
    links, room = [], record["room_id"]
    cache = {} if cache is None else cache
    if room not in cache:
        cache[room] = list(chat_chain.iter_room_rows(root, room))
    for address, row, pos in cache[room]:
        if pos <= end or str(row.get("task_id") or "") != task_id:
            continue
        host = row.get("type") in ("task_summary", "project_completion_summary")
        final = row.get("direction") == "out" and not row.get("is_progress") and (
            row.get("terminal_origin") or row.get("task_terminal_status") or row.get("task_phase") == "finalizing")
        if host or final:
            addr = chat_chain.format_address(address)
            speaker = "host summary" if host else "task final report"
            status = row.get("status") or row.get("task_terminal_status") or "status not recorded"
            links.append(f"- Linked {speaker} of task {task_id} ({status}); not page coverage; "
                         f"memory_read(room_id='{record['room_id']}', rows=true, from='{addr}', to='{addr}')")
    return links
