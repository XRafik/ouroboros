"""Verdict-neutral storage and accounting for the Safety Supervisor."""

import logging
import pathlib
from typing import Any, Dict, Optional

from ouroboros.utils import utc_now_iso

log = logging.getLogger(__name__)

def _safety_drive_root(ctx: Optional[Any]) -> pathlib.Path:
    """Where this safety call's observability records belong.

    The context owns the answer. Without one, the process's configured data root
    is the SSOT — never the old cwd-relative ``../data``, which names whatever
    directory happens to sit beside the current working directory and only
    resolves to the real root by coincidence of the dev layout (a safety call
    made with ``ctx=None`` — the extension/MCP dispatch shape — wrote its
    observability rows there). Read late off the module so test isolation and
    runtime rebinding are honored, the same resolution order the review
    surfaces already use.
    """
    root = getattr(ctx, "drive_root", None) if ctx is not None else None
    if root:
        return pathlib.Path(root)
    from ouroboros import config

    return pathlib.Path(config.DATA_DIR)


def _record_safety_usage(ctx: Optional[Any], usage_payload: Dict[str, Any]) -> None:
    """Charge a safety call that had no event queue to report on.

    The queue is the normal path; this is the fallback. The ledger writer is
    INJECTED by the context when it has one (the ``update_budget_from_usage``
    attribute the supervisor event context already carries), so a caller that
    owns its own accounting is charged where it lives. A context without one
    falls back to this process's own supervisor state, imported AT CALL TIME so
    the safety module — which runs inside every worker and on every tool call —
    keeps no import-time dependency on the supervisor package, exactly as the
    six sibling call sites of this writer already do.
    """
    sink = getattr(ctx, "update_budget_from_usage", None) if ctx is not None else None
    if callable(sink):
        sink(usage_payload)
        return
    from supervisor.state import update_budget_from_usage

    update_budget_from_usage(usage_payload)


def _emit_durable_safety_event(ctx: Optional[Any], event: Dict[str, Any]) -> None:
    """Emit a safety audit event durably AT THE MOMENT of the decision (v6.54.3).

    The canonical durable pattern (mirrors control._emit_swarm_fanout): a DIRECT
    append into the drive's events.jsonl — the per-worker log sink forwards
    appended lines to the live dashboard, so no separate queue put is needed and
    a queued-but-undrained event can never be lost to a worker death (review
    round 9, P3). The event_queue is only the last resort for contexts with no
    drive_logs at all."""
    payload = {
        "task_id": str(getattr(ctx, "task_id", "") or "") if ctx is not None else "",
        "ts": utc_now_iso(),
        **event,
    }
    try:
        drive_logs = getattr(ctx, "drive_logs", None) if ctx is not None else None
        if callable(drive_logs):
            from ouroboros.utils import append_jsonl

            if append_jsonl(drive_logs() / "events.jsonl", payload):
                return
            # append_jsonl answers whether the row landed (its documented contract for
            # important events); a False here means the durable half of the disclosure
            # is missing, so fall through to the queue rather than returning silently.
            log.error(
                "durable safety event %s not persisted; falling back to event queue",
                event.get("type") or "?",
            )
        eq = getattr(ctx, "event_queue", None) if ctx is not None else None
        if eq is not None:
            eq.put_nowait(payload)
    except Exception:
        # The durable audit is a P3 invariant for waved-through safety decisions —
        # a lost emit must not be TRULY silent. Never fatal (a failed audit write
        # must not break a task), but escalate to error so the loss is itself
        # traced (adversarial review r1 #21).
        log.error("failed to emit durable safety event %s", event.get("type") or "?", exc_info=True)


def _emit_safety_mode_skip(ctx: Optional[Any], tool_name: str, mode: str, policy: str) -> None:
    """Durable audit for a safety LLM check waved through by a non-full owner mode.

    P3: an advisory/off mode is legitimate ONLY while every decision it waves
    through leaves a loud, durable trace at the moment it happens (review round 1)."""
    _emit_durable_safety_event(ctx, {
        "type": "safety_mode_skip",
        "tool": tool_name,
        "safety_mode": mode,
        "policy": policy,
    })
