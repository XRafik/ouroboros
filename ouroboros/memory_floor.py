"""One start allowance and an ordered walk over an immutable memory snapshot.

After the start, only a physical deficit narrows the selected forms. Owner rows
without carried commitments may spend the work room, but never silently disappear.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ouroboros import context_budget
from ouroboros.chat_chain import parse_address
from ouroboros import memory_view as mv
from ouroboros import memory_view_legacy as legacy
from ouroboros.utils import estimate_tokens

LADDER = ("F1", "F1b", "F6r", "F6", "F6a", "F3", "F2", "F4", "F7p", "F7", "F5")
MODES = ("max", "low", "nano")
_COLLAPSING = ("F1", "F1b", "F6a")
_SHOWN = (("F2", "{} of my replies"), ("F7", "{} owner rows"), ("F7p", "{} other spoken rows"),
          ("F6r", "{} other rooms as ranges"), ("F6", "{} other rooms as directory lines"),
          ("F6a", "{} other rooms in an aggregate"), ("F4", "{} room records"),
          ("F5", "{} pages, parts or accounts of my story"), ("F3", "{} retold rooms"),
          ("F1", "{} task fact lines"), ("F1b", "{} quiet rooms"))
_PATH_CASES = ((), ("enable_tools",), ("list_available_tools",), ("chronicle_write", "list_available_tools"))
_SEALING_TOOLS = frozenset({"chronicle_write", "enable_tools"})  # sent, or loadable through enable_tools


def view_tokens(text: str) -> int:
    """The host's estimate of a text inside a request: its JSON-escaped characters / 4."""
    return estimate_tokens(json.dumps(str(text), ensure_ascii=False)) if text else 0


def floor_elements(snapshot: mv.MemoryViewSnapshot) -> List[Tuple[str, str, str, str]]:
    """Ordered addressable forms, oldest first. Core and governing words have no rung."""
    if not snapshot.active:
        return []
    room = snapshot.room or {}
    lane1, lane2 = room.get("lane1") or [], room.get("lane2") or []
    quiet = [r for r in snapshot.live_rooms if not r["notes"] and not r["words"]]
    others = [r for r in snapshot.live_rooms if r not in quiet]
    mine = sorted((i for i in lane1 if i["kind"] == "ouroboros"), key=lambda i: i["pos"])
    steps = {
        "F1": [(i["first"], i["line"], "" if n else mv._facts_line(room, [i])) for n, i in enumerate(lane2)],
        "F1b": [(r["room_id"], mv._directory_room(r) if r.get("directory") else "\n".join(mv._live_room(r)),
                  "" if n else mv._rooms_line([r])) for n, r in enumerate(quiet)],
        "F6r": [(r["room_id"], "\n".join(mv._live_room(r)), mv._range_room(r)) for r in others if not r.get("directory")],
        "F6": [(r["room_id"], mv._range_room(r), mv._directory_room(r)) for r in others if not r.get("directory")],
        "F6a": [(r["room_id"], mv._directory_room(r), "" if n or quiet else mv._rooms_line([r])) for n, r in enumerate(others)],
        "F3": [(rid, "\n".join(map(legacy.retold_record, group)), legacy.room_pointer(group))
               for rid, group in legacy.pointer_rooms(snapshot.story).items()],
        "F2": [(i["address"], i["line"], mv._row_pointer(i, "my reply")) for i in mine],
        "F4": [(i["id"], mv._retold(i), mv._retold(i, True)) for i in [*room.get("legacy", ()), *room.get("under_parts", ())]],
        "F7p": [(i["address"], i["line"], mv._row_pointer(i, "words")) for i in lane1
                if i["kind"] != "ouroboros" and not i.get("owner_side", i["kind"] == "human")],
        "F7": [(i["address"], i["line"], mv._row_pointer(i, "words")) for i in lane1
               if i.get("owner_side", i["kind"] == "human") and not i.get("immune")],
        "F5": [(e["id"], "\n".join(mv._page_lines(e)), mv._page_pointer(e))
               for e in snapshot.story if e.get("kind") != "legacy" and not e.get("told_by")],
    }
    return [(step, ident, whole, short) for step in LADDER for ident, whole, short in steps[step]
            if step in _COLLAPSING or len(short) < len(whole)]


def degradable_elements(snapshot: mv.MemoryViewSnapshot) -> List[Tuple[str, str, int, int]]:
    """``(step, element id, tokens whole, tokens by address)`` in ladder order: each element's known saving."""
    return [(step, ident, view_tokens(whole), view_tokens(short))
            for step, ident, whole, short in floor_elements(snapshot)]


def floor_allowances(*, window_tokens: Optional[int], output_reserve_tokens: Optional[int], non_memory_tokens: int,
                     target_tokens: Optional[int] = None, calibration_ratio: float = 1.0,
                     work_room_levels: int = 1, boundary_tokens: Optional[int] = None) -> Dict[str, Optional[int]]:
    """One start bound for all unsolicited material; a physical bound for uncovered owner rows."""
    frame = dict(output_reserve_tokens=output_reserve_tokens, non_memory_tokens=non_memory_tokens,
                 calibration_ratio=calibration_ratio, margin_count=work_room_levels, boundary_tokens=boundary_tokens)
    physical = context_budget.request_context_budget(window_tokens=window_tokens, **frame)
    start = context_budget.request_context_budget(window_tokens=window_tokens, target_tokens=target_tokens, **frame)
    return {"margin": start["with_margin_tokens"], "physical": physical["without_margin_tokens"],
            "budget": start["with_margin_tokens"] if target_tokens else None}


def fit_memory_view(snapshot: mv.MemoryViewSnapshot, allowances: Mapping[str, Optional[int]], *,
                    kept: mv.FloorLevel = mv.FULL_VIEW, saving: int = 0) -> mv.FloorLevel:
    """One ordered walk, then give back new cuts that fit. Previously chosen forms stay selected."""
    elements = degradable_elements(snapshot)
    old = {(step, ident) for step, ids in kept.addressed for ident in ids}
    taken = set(old)
    current = view_tokens(mv.render_story(snapshot, kept)) + view_tokens(mv.render_room(snapshot, kept))
    bounds = [b for b in (allowances.get("margin"), allowances.get("budget")) if b is not None]
    bound = min(bounds) if bounds else None
    target = min(bound if bound is not None else current, current - saving) if saving else bound
    owner = {i["address"]: i for i in (snapshot.room or {}).get("lane1", ())}
    added = []
    for step, ident, whole, short in elements:
        if (step, ident) in taken or target is None or current <= target:
            continue
        if step == "F7" and not owner[ident].get("carried"):
            physical = allowances.get("physical")
            if physical is None or current <= physical:
                continue
        delta = max(0, whole - short)
        taken.add((step, ident))
        added.append((step, ident, delta))
        current -= delta
    # A coarse final cut can leave space for an earlier element; give it back without unfolding kept choices.
    for step, ident, delta in reversed(added):
        if target is not None and current + delta <= target:
            taken.remove((step, ident))
            current += delta
    budget = allowances.get("budget") is not None and allowances.get("budget") == bound
    return mv.FloorLevel(tuple((s, tuple(i for step, i, *_ in elements if step == s and (s, i) in taken))
                              for s in LADDER if any(step == s for step, _ in taken)),
                         by_budget=kept.by_budget + (len(taken - old) if budget else 0))


def kept_level(snapshot: mv.MemoryViewSnapshot, facts: Mapping[str, Any]) -> mv.FloorLevel:
    """The level a projection's floor fact names: each step's first ``count`` elements, in ladder order."""
    floor = (facts or {}).get("floor") or {}
    if "addressed" in floor:
        return mv.FloorLevel(tuple((step, tuple(ids)) for step, ids in floor["addressed"]),
                             by_budget=int(floor.get("by_budget") or 0))
    counts = dict(floor.get("steps") or {})
    ids: Dict[str, List[str]] = {}
    for step, ident, _whole, _short in floor_elements(snapshot):
        if len(ids.setdefault(step, [])) < int(counts.get(step) or 0):
            ids[step].append(ident)
    return mv.FloorLevel(tuple((step, tuple(ids[step])) for step in LADDER if ids.get(step)),
                         by_budget=int(floor.get("by_budget") or 0))


def memory_read_path(tool_names: Optional[Iterable[str]]) -> str:
    """How this request reaches ``memory_read``, read from the names of the schemas it sends.

    Nothing when it sends ``memory_read`` or its schemas are not known (``None``: no claim);
    ``enable_tools`` when it sends that; otherwise the parent, who can read an address for me,
    and ``list_available_tools`` when it sends that. A fact of the request, never of a role.
    """
    if tool_names is None:
        return ""
    names = set(tool_names)
    if "memory_read" in names:
        return ""
    if "enable_tools" in names:
        return "(memory_read is reachable through enable_tools)"
    listing = "list_available_tools shows what this task can call, and " if "list_available_tools" in names else ""
    return f"(memory_read is not among this request's tools; {listing}my parent task can read any address I name to it)"


def floor_note(level: mv.FloorLevel, *, window_tokens: Optional[int], mode: str, target_tokens: Optional[int] = None,
               lowered_from: Optional[str] = None, tool_names: Optional[Iterable[str]] = None,
               budget_mode: Optional[str] = None) -> str:
    """``### Physical floor``: a fact and a possibility for the mind, exactly when a step past F1/F1b ran
    or the window lowered the task's mode; never an instruction or a threshold. In Nano it
    closes with how this request reaches ``memory_read`` (``tool_names``: the schemas it sends). The
    sealing possibility is named only when the request can call ``chronicle_write``: it sends it or
    ``enable_tools`` (unknown schemas keep it); like the path line, a fact of the request, not a role.
    Cuts are retained history, not a claim that the current mode cannot hold the full memory. The
    window names the cut's frame; a fitting route keeps this note's bytes, and the round's facts
    name the acting window. The mode names this view and the mode the task runs in, lowered at its
    start or on a later route; ``budget_mode`` (default ``mode``) names the owner's target that took
    the budget cuts."""
    names = None if tool_names is None else tuple(tool_names)
    counts = dict(level.steps)
    asked = set(counts) - set(_COLLAPSING)
    if not asked and not lowered_from:
        return ""
    lines, name = ["### Physical floor"], mode.capitalize()
    if asked:
        bounds = ([f"the window ({window_tokens} tokens)"]
                  if sum(counts.values()) > level.by_budget else []) + (
            [f"the {(budget_mode or mode).capitalize()} mode budget ({target_tokens} tokens)"] if level.by_budget else [])
        subject = " and ".join(bounds)
        shown = ", ".join(text.format(counts[step]) for step, text in _SHOWN if counts.get(step))
        sealing = (" Sealing a closed part of the open conversation as a page (chronicle_write kind=page) or folding "
                   "old pages (kind=part) can carry the commitments in my own words."
                   if names is None or _SEALING_TOOLS & set(names) else "")
        lines.append(f"This {name} view retains memory cuts for {subject}. "
                     f"Shown above only by address: {shown}. The retained sources remain readable: memory_read reads "
                     f"each.{sealing}")
    if lowered_from:
        lines.append("Low: the books did not fit beside the story and the work room.")
    path = memory_read_path(names) if mode == "nano" else ""
    return "\n".join(lines + [path] if path else lines)


def view_facts(snapshot: mv.MemoryViewSnapshot, level: mv.FloorLevel, *, window_tokens: Optional[int], mode: str,
               allowances: Mapping[str, Optional[int]], target_tokens: Optional[int] = None,
               lowered_from: Optional[str] = None) -> Dict[str, Any]:
    """The floor fact of one projection, kept in the task trace: steps, boundaries, what is shown by address.

    ``newest_addressed_row`` is the newest row of this room that F1, F2 or F7 shows only by
    address; ``pointer_records`` the records F4 and F5 show by a pointer. No list of rows.
    """
    gone = {step: set(ids) for step, ids in level.addressed}
    room = snapshot.room or {}
    rows = [(item["last_pos"], item["last"]) for item in room.get("lane2") or () if item["first"] in gone.get("F1", ())]
    addressed = gone.get("F2", set()) | gone.get("F7", set()) | gone.get("F7p", set())  # once, not per lane-1 row
    rows += [(item["pos"], item["address"]) for item in room.get("lane1") or () if item["address"] in addressed]
    status = snapshot.legacy_blocks or {}
    return {"role": snapshot.spec.role, "room_id": snapshot.spec.room_id,
            "floor": {"steps": dict(level.steps), "addressed": level.addressed, "window_tokens": window_tokens, "mode": mode,
                      "allowance_tokens": allowances.get("margin"), "physical_allowance_tokens": allowances.get("physical"),
                      "target_tokens": target_tokens, "budget_allowance_tokens": allowances.get("budget"),
                      "by_budget": level.by_budget, "mode_switch": {"from": lowered_from, "to": mode} if lowered_from else None,
                      "newest_addressed_row": parse_address(max(rows)[1]) if rows else None,
                      "pointer_records": [ident for step, ids in level.addressed if step in ("F4", "F5") for ident in ids]},
            "story_status": {"folded": status.get("folded", 0), "total": status.get("total", 0)}}


def render_view_for_mode(snapshot: mv.MemoryViewSnapshot, *, mode: str, owner_mode: str, window_tokens: Optional[int],
                         known_window: bool, output_reserve: Optional[int], ratio: float, non_memory_tokens: int,
                         lowered_from: Optional[str] = None, tool_names: Optional[Iterable[str]] = None,
                         kept: Optional[mv.FloorLevel] = None, saving: int = 0, boundary_tokens: Optional[int] = None) -> Tuple[str, str, Dict[str, Any]]:
    """``(story text, room text, facts)`` of one mode's projection, the floor decided once.

    The window counts only when known and fresh (``known_window``). An owner target binds
    only the mode the owner selected: task-local Low and a mode the window lowered have
    none. The reply reserve is the mode's (Nano keeps its own headroom). ``tool_names`` are
    the schemas this mode's request sends, which the floor note reads (``memory_read_path``).
    ``kept`` narrows a view already shown: from its level, against the window minus the reply
    reserve alone -- no working margin, no target -- so nothing it addressed comes back.
    What ``kept.by_budget`` counts the owner's mode target took (only it carries one), so the note
    and the fact name that budget in whatever mode the view is narrowed, hop after hop.
    """
    target, reserve = context_budget.context_mode_limits(mode, owner_mode, output_reserve)
    if kept is not None and kept.by_budget:
        target = context_budget.context_mode_limits(owner_mode, owner_mode, output_reserve)[0]
    window = int(window_tokens) if known_window and window_tokens else None
    allowances = floor_allowances(window_tokens=window, output_reserve_tokens=reserve, non_memory_tokens=non_memory_tokens,
                                  target_tokens=None if kept is not None else target, calibration_ratio=ratio,
                                  work_room_levels=snapshot.spec.work_room_levels, boundary_tokens=boundary_tokens)
    if kept is not None:
        allowances = {**allowances, "margin": allowances["physical"]}
    level = fit_memory_view(snapshot, allowances, kept=kept or mv.FULL_VIEW, saving=saving)
    note = floor_note(level, window_tokens=window, mode=mode, target_tokens=target, lowered_from=lowered_from,
                      tool_names=tool_names, budget_mode=owner_mode)
    actual = view_tokens(mv.render_story(snapshot, level)) + view_tokens(mv.render_room(snapshot, level))
    if allowances["margin"] is not None and actual > allowances["margin"]:
        note += ("\nStart room is smaller than requested: uncovered owner words remain in view; "
                 "only physical pressure can turn their oldest rows into named addresses.")
    return (mv.render_story(snapshot, level), mv.render_room(snapshot, level, floor_note=note),
            view_facts(snapshot, level, window_tokens=window, mode=mode, allowances=allowances, target_tokens=target,
                       lowered_from=lowered_from))


TRACE_FIELDS = ("role", "room_id", "floor", "story_status")  # what a task trace keeps of a view receipt


def trace_facts(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    """The part of a view receipt the task context and the task trace keep (``VIEW_TRACE_KEY``)."""
    return {key: receipt[key] for key in TRACE_FIELDS if key in receipt}


def view_receipt(snapshot: mv.MemoryViewSnapshot, story: str, room: str, facts: Mapping[str, Any]) -> Dict[str, Any]:
    """A projection's view fact: the floor fact plus the spec, the chronicle's state and block sizes.

    ``role``, ``room_id``, ``floor`` and ``story_status`` are what a task trace keeps
    (``memory_inventory.VIEW_TRACE_KEY``); the rest is the receipt's (estimator tokens).
    """
    return {**facts, "spec": dataclasses.asdict(snapshot.spec), "store_status": dict(snapshot.store_status),
            "legacy_frontier_status": snapshot.frontier.get("status"),
            "blocks": {"story_tokens": view_tokens(story), "room_tokens": view_tokens(room),
                       "live_rooms": len(snapshot.live_rooms), "marks": len(snapshot.marks)}}


def minimal_view_tokens(snapshot: mv.MemoryViewSnapshot, *, window_tokens: Optional[int] = None) -> int:
    """The shortest view of my memory: every degradable element by address, with the longest floor note."""
    taken: Dict[str, List[str]] = {}
    for step, ident, _whole, _short in floor_elements(snapshot):  # grouped in ladder order
        taken.setdefault(step, []).append(ident)
    level = mv.FloorLevel(tuple((step, tuple(ids)) for step, ids in taken.items()))
    note = max((floor_note(level, window_tokens=window_tokens, mode="nano", lowered_from="max", tool_names=names)
                for names in _PATH_CASES), key=view_tokens)  # an upper bound, whatever schemas it sends
    return view_tokens(mv.render_story(snapshot, level)) + view_tokens(mv.render_room(snapshot, level, floor_note=note))
