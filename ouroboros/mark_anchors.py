"""Marks I tie to an action meet me in the result of the first such call in a task.

A mark may carry an ``anchor`` its author chose: a tool name, optionally with text the
call's arguments must contain, or a file or directory path a call names. The host
compares literally and adds the mark's own words to that call's result once per
task, as a host note behind the producer's payload (``tool_result._HOST_NOTE_SEPARATOR``,
so text readers still recover the payload); it judges nothing, never refuses or delays
the call, and a room mark meets only the work of the room the task is in now. Reading
marks is best effort: an unreadable chronicle leaves the result as it was.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, Iterator, List

log = logging.getLogger(__name__)

_CACHE_ATTR = "_anchored_marks"
_DELIVERED_ATTR = "_anchored_marks_delivered"


def anchor_problem(anchor: Any) -> str:
    """Empty for a well-formed anchor, otherwise what is wrong with it."""
    if not isinstance(anchor, dict) or not anchor:
        return "anchor is an object: {tool, text?} or {path}"
    keys = set(anchor)
    if "tool" in keys and keys <= {"tool", "text"}:
        ok = all(isinstance(anchor[key], str) and anchor[key].strip() for key in keys)
        return "" if ok else "anchor tool and text are non-empty strings"
    if keys == {"path"}:
        return "" if isinstance(anchor["path"], str) and anchor["path"].strip() else "anchor path is a non-empty string"
    return "anchor is {tool, text?} or {path}"


def describe(anchor: Dict[str, Any]) -> str:
    if "path" in anchor:
        return f"the path {anchor['path']}"
    return str(anchor.get("tool")) + (f" with {anchor['text']!r}" if anchor.get("text") else "")


def _strings(value: Any, depth: int = 0) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif depth < 4 and isinstance(value, dict):
        for item in value.values():
            yield from _strings(item, depth + 1)
    elif depth < 4 and isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item, depth + 1)


def _names_path(anchor_path: str, value: str) -> bool:
    """A call argument names the anchored file or directory, relative or absolute."""
    path = anchor_path.strip().replace("\\", "/").rstrip("/")
    path = path[2:] if path.startswith("./") else path
    text = value.replace("\\", "/")
    return bool(path) and (text == path or text.startswith(path + "/") or text.endswith("/" + path)
                           or "/" + path + "/" in text)


def matches(anchor: Dict[str, Any], tool: str, args: Any) -> bool:
    """A path anchor meets an argument that is one path naming it (never a path inside file text or
    a sentence); a tool anchor meets that tool, and its text an argument value or a command's words."""
    if "path" in anchor:
        return any(_names_path(str(anchor["path"]), value) for value in _strings(args) if value and not
                   any(char.isspace() for char in value))
    if anchor.get("tool") != tool:
        return False
    text = anchor.get("text")
    return not text or str(text) in " ".join(_strings(args))


def _anchored_marks(ctx: Any) -> List[Dict[str, Any]]:
    """This task's anchored marks (its room's and the global ones), read again only when the
    task's project placement changes (a move to another project changes its room)."""
    from ouroboros.chronicle_store import ChronicleStore
    from ouroboros.dialogue_evidence import own_room_chat
    from ouroboros.project_facts import placed_project_id
    from ouroboros.tool_access import canonical_data_root

    placement = str(placed_project_id(ctx) or "")
    cached = getattr(ctx, _CACHE_ATTR, None)
    if cached is not None and cached[0] == placement:
        return cached[1]
    root = canonical_data_root(ctx)
    store = ChronicleStore(root)
    receipt = store.activation()  # read only: marks exist only on an activated chronicle
    if not isinstance(receipt, dict) or receipt.get("kind") != "activation":
        return []
    room = own_room_chat(ctx, root)
    rows = store.active_marks(None) if room is None else store.active_marks(str(room), include_global=True)
    marks = [mark for mark in rows if isinstance(mark.get("anchor"), dict) and not anchor_problem(mark["anchor"])
             and (room is not None or mark.get("scope") == "global")]
    setattr(ctx, _CACHE_ATTR, (placement, marks))
    return marks


def deliver_anchored_marks(ctx: Any, tool: str, args: Any, result: Any) -> Any:
    """``result`` with the words of each anchored mark this call meets for the first time in the task."""
    if ctx is None:
        return result
    try:
        if tool == "memory_mark":
            setattr(ctx, _CACHE_ATTR, None)  # a new or released mark acts from the next call
            return result
        delivered = getattr(ctx, _DELIVERED_ATTR, None)
        if delivered is None:
            delivered = set()
            setattr(ctx, _DELIVERED_ATTR, delivered)
        notes = []
        for mark in _anchored_marks(ctx):
            mark_id = str(mark.get("id") or "")
            if mark_id in delivered or not matches(mark["anchor"], tool, args):
                continue
            delivered.add(mark_id)
            notes.append(f"⚠️ Mark I tied to {describe(mark['anchor'])} ({mark_id}): "
                         f"{str(mark.get('text') or '').strip()}")
        if not notes:
            return result
        note = "\n".join(notes)
        return dataclasses.replace(
            result, text=f"{result.text}\n\n{note}",
            producer_text=result.producer_text if result.producer_text is not None else result.text,
            host_annotations=tuple(result.host_annotations) + (note,))
    except Exception:
        log.debug("anchored marks: delivery skipped for %s", tool, exc_info=True)
        return result
