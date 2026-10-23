"""Collect changed plan candidates at zero spend; a pending seat remains the debt.

Task writes and durable producer publications queue the candidate's own signature.
The child acknowledges successful examinations; failures stay due for its next pass.
Legacy classification and explicit repair select all candidates once; unrelated task
completions never wake collection.
"""
import logging

from ouroboros import maintenance_jobs, store
from ouroboros.utils import machine_json

JOB = "ended_plan_asks"
SOURCE = "plan_collection_source"  # obsolete install-wide publication marker
CHANGED = "plan_collection_changed"


def task_written(txn, task_id, columns):
    if not columns:
        return
    if columns.get("plan_collection_pending") != 0:
        txn.put_row(CHANGED, task_id, {"signature": [columns.get("write_seq"), columns.get("updated_at")]})
    else:
        txn.delete_row(CHANGED, task_id)


def producer_published(root, token):
    """Best-effort wake after durability; pending-job repair rediscovers missed replies."""
    try:
        with store.acquisition_budget(0), store.open_store(root, write=True) as txn:
            task_id = str(token[0])
            if txn.row(task_id, "plan_collection_pending") != 0:
                txn.put_row(CHANGED, task_id, {"producer": token})
        from ouroboros.maintenance import child
        child.request()
    except Exception:
        logging.getLogger(__name__).debug("Plan publication awaits collection repair", exc_info=True)


def due(root, row, facts, child):
    if row.get("state") == "pending" or not row.get("addressed"):
        return True
    with store.open_store(root, write=False) as txn:
        return txn.conn.execute("SELECT 1 FROM obligations WHERE set_name=? LIMIT 1", (CHANGED,)).fetchone() is not None


def run(root, should_stop):
    from ouroboros.late_review_marks import _collect_ended_plan_asks
    from ouroboros.task_store import plan_collection_candidates

    row = maintenance_jobs.job(root, JOB) or {}
    complete = False
    examined = set()

    def selected():
        nonlocal complete
        if row.get("state") == "pending" or not row.get("addressed"):
            from itertools import chain
            with store.open_store(root, write=False) as txn:
                queued = [item[0] for item in txn.conn.execute(
                    "SELECT id FROM obligations WHERE set_name=? ORDER BY id", (CHANGED,))]
            identities = chain(plan_collection_candidates(root, stop=should_stop), queued)
        else:
            with store.open_store(root, write=False) as txn:
                identities = [item[0] for item in txn.conn.execute(
                    "SELECT id FROM obligations WHERE set_name=? ORDER BY id", (CHANGED,))]
        seen = set()
        for task_id in identities:
            if task_id in seen:
                continue
            seen.add(task_id)
            with store.open_store(root, write=False) as txn:
                observed = txn.get_row(CHANGED, task_id)
            yield task_id
            if task_id in examined and observed is not None:
                with store.open_store(root, write=True) as txn:
                    txn.conn.execute("DELETE FROM obligations WHERE set_name=? AND id=? AND facts=?",
                                     (CHANGED, task_id, machine_json(observed)))
        complete = seen <= examined

    settled = _collect_ended_plan_asks(root, should_stop, candidates=selected(), on_examined=examined.add)
    state = "done" if complete and not should_stop() else "pending"
    with store.open_store(root, write=True) as txn:
        maintenance_jobs.forget_in(txn, JOB, "inputs")
        maintenance_jobs.record_in(txn, JOB, state=state, addressed=True)
        txn.conn.execute("DELETE FROM meta WHERE key=?", (SOURCE,))
    return {"state": state, "items": settled}
