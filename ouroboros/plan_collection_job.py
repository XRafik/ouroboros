"""Ended plan asks collect retained replies in the maintenance child, at zero spend.

The terminal-write counter, producer publication, and startup recovery generation
are facts that wake collection. Unchanged pending seats and unreadable outcomes rest;
the pending seat remains the debt. An explicit pending job is the repair entry point.
"""
from ouroboros import maintenance_jobs, store

JOB = "ended_plan_asks"
SOURCE = "plan_collection_source"


def producer_published(root, token):
    """One retained plan-review completion wakes the child after its manifest is durable."""
    with store.open_store(root, write=True) as txn:
        if txn.meta(SOURCE) != token:
            txn.set_meta(SOURCE, token)
    from ouroboros.maintenance import child
    child.request()


def _inputs(root):
    with store.open_store(root, write=False) as txn:
        return [txn.meta(store.TERMINAL_WRITES), txn.meta(SOURCE), txn.meta("startup_recovery")]


def due(root, row, facts, child):
    return row.get("state") == "pending" or row.get("inputs") != _inputs(root)


def run(root, should_stop):
    from ouroboros.late_review_marks import _collect_ended_plan_asks

    inputs = _inputs(root)
    settled = _collect_ended_plan_asks(root, should_stop)
    state = "pending" if should_stop() else "done"
    maintenance_jobs.record(root, JOB, state=state, inputs=inputs)
    return {"state": state, "items": settled}
