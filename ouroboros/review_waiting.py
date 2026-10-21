"""Chosen helper terminals and delivery cursors of one retained review wait.

Readiness never consumes a fact. A complete transcript insertion stages its
cursor; the working checkpoint makes that acknowledgement durable. The late
room duty has an independent lifetime and is never discharged here.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import logging

log = logging.getLogger(__name__)


def select_helpers(ctx):
    """Pin this author's outstanding direct children and ordinary delegated runs."""
    from ouroboros.model_sleep import _canonical_root, _owned_runs
    from ouroboros.task_store import task_facts
    from ouroboros.task_status import SETTLED_STATUSES
    from ouroboros.delegate_custody import TERMINAL_STATES

    prior = getattr(ctx, "_left_review_wait", None)
    if isinstance(prior, dict):
        # Legacy waits mean the whole wave, not a newly inferred helper roster.
        state = {key: copy.deepcopy(prior.get(key) or ([] if key != "selection" else {}))
                 for key in ("selection", "seen_helpers", "seen_outcomes")}
    else:
        state = {"selection": {"tasks": [], "runs": []}, "seen_helpers": [], "seen_outcomes": []}
        try:
            rows = task_facts(_canonical_root(ctx), where="parent_task_id=?", params=(str(ctx.task_id),))
            state["selection"]["tasks"] = [tid for tid, row in rows.items()
                                            if row["status"] not in SETTLED_STATUSES]
        except Exception:
            log.debug("Review child selection unavailable", exc_info=True)
        try:
            state["selection"]["runs"] = [rid for rid, run in _owned_runs(ctx).items()
                                           if not run.review_owned and not run.settled
                                           and run.terminal_state not in TERMINAL_STATES]
        except Exception:
            log.debug("Review helper selection unavailable", exc_info=True)
    ctx._review_wait_selection = state
    return copy.deepcopy(state)


def ready_helpers(ctx, state):
    from ouroboros.model_sleep import terminal_readiness
    from ouroboros.store import acquisition_budget

    try:
        with acquisition_budget(0):
            return terminal_readiness(ctx, state.get("selection") or {}, state.get("seen_helpers") or (), ordinary_only=True)
    except Exception:
        log.debug("Review helper readiness unavailable", exc_info=True)
        return []


def save_wait(ctx, record_id, state):
    from ouroboros.review_ledger import ledger_root, revise_record

    def merge(record):
        old = record.get("waiting") or {}
        record["waiting"] = {**copy.deepcopy(state), **{key: sorted(set(old.get(key) or ()) | set(state.get(key) or ()))
                             for key in ("seen_helpers", "seen_outcomes")}}
        return record
    record = revise_record(ledger_root(ctx), record_id, merge)
    if record and (record.get("waiting") or {}).get("duty_id"):
        from ouroboros.late_review_marks import update_wait_cursors
        update_wait_cursors(ledger_root(ctx), record["waiting"]["duty_id"], record["waiting"])
    return record


def outcome_ids(record):
    from ouroboros.review_ledger import seat_open

    outcomes = []
    for row in record.get("rows") or ():
        if seat_open(row):
            continue
        outcome = row.get("outcome_id") or hashlib.sha256(json.dumps(
            {key: row.get(key) for key in ("status", "answers", "source_refs")}, sort_keys=True).encode()).hexdigest()
        outcomes.append(f"{record['record_id']}:{row.get('operation_id') or row['seat_id']}:{outcome}")
    return outcomes


def publish_delivery(ctx, text, record):
    """Publish exact receipt metadata beside the result; producing it is not an ACK."""
    from ouroboros.tools.tool_result import ToolResult, _publish_tool_result, _published_tool_result, _classify_legacy_text

    record_id = str(record.get("record_id") or "")
    if not record_id:
        return text
    state = (getattr(ctx, "_left_review_wait", None) or getattr(ctx, "_review_wait_selection", None)
             or record.get("waiting") or {})
    helpers = ready_helpers(ctx, state)
    receipt = {"record_id": record_id, "helpers": [row["id"] for row in helpers],
               "outcomes": outcome_ids(record)}
    suffix = "\n\n[Helper results] " + json.dumps(helpers) if helpers else ""
    prior = _published_tool_result(ctx, None)
    if not isinstance(prior, ToolResult) or prior.text != text:
        status, code, meta = _classify_legacy_text(text)
        prior = ToolResult(status=status, code=code, text=text, meta=meta)
    return _publish_tool_result(ctx, dataclasses.replace(prior, text=text + suffix,
                                meta={**prior.meta, "review_delivery": receipt}))


def acknowledge_delivery(ctx, receipt):
    """Called after complete transcript insertion, never from a readiness peek."""
    from ouroboros.review_ledger import ledger_root, load_record
    from ouroboros.working_checkpoint import defer_content_ack

    record_id = str(receipt.get("record_id") or "")
    try:
        record = load_record(ledger_root(ctx), record_id)
    except (OSError, ValueError):
        log.warning("Review delivery cursor stays unacknowledged", exc_info=True)
        return
    if not record or record.get("task_id") != str(ctx.task_id):
        return
    state = copy.deepcopy(record.get("waiting") or getattr(ctx, "_review_wait_selection", None) or {})
    for target, source in (("seen_helpers", "helpers"), ("seen_outcomes", "outcomes")):
        state[target] = sorted(set(state.get(target) or ()) | set(receipt.get(source) or ()))
    ctx._review_wait_selection = state
    wait = getattr(ctx, "_left_review_wait", None)
    if isinstance(wait, dict) and wait.get("record_id") == record_id:
        wait.update({key: copy.deepcopy(state[key]) for key in ("selection", "seen_helpers", "seen_outcomes")
                     if key in state})
    defer_content_ack(ctx, lambda: save_wait(ctx, record_id, state))


def append_helper_notice(ctx, messages):
    wait = getattr(ctx, "_left_review_wait", None) or {}
    ready = ready_helpers(ctx, wait)
    if ready:
        messages.append({"role": "user", "content": "[Helper results] " + json.dumps(ready)})
        acknowledge_delivery(ctx, {"record_id": wait.get("record_id"), "helpers": [row["id"] for row in ready]})
