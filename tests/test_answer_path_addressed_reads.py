"""The paths that answer the owner read addressed facts, never unrelated history.

ARCHITECTURE §10 invariant 10 and BIBLE P5: a current answer is read from the facts it
names. On 22.10 three readers on the threads that answer did history-sized work: the
``send_message`` handler's receipt capture listed every evidence-pack sidecar (two
supervisor-loop stalls of 125.7 s and 169.0 s), the owner-message intake read every
task's typed row to offer the newest root results (a 19.5 s hold), and the consciousness
tick read its allowance window on the loop (holds up to 23 s).

Each boundary is driven through its real entry point on two roots that hold the same
current facts and k=1 or k=30 units of unrelated history, counted by the cost-contract
meter (``tests/_cost_meter.py``) and compared by the contract's own rule
(``tests/test_cost_contract.py::contract_breaches``: equal work, a logarithmic SQLite
allowance). A warm-up on each root first takes the process-wide first-use costs (imports,
memos), so the counted call is the steady first pass of the boundary itself. Every guard
has a companion that shows the boundary still does its job on both sizes.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from types import SimpleNamespace
from typing import Any, Callable, Dict

import pytest

from tests._cost_meter import CostMeter, tagged
from tests.test_cost_contract import K_SMALL, contract_breaches

pytestmark = pytest.mark.scale

K_LARGE = 30
TAG = "answer_path"


def _flat(tmp_path, monkeypatch, build: Callable[[Any, int], Any],
          boundary: Callable[[Any, Any], Callable[[], Any]]) -> Dict[int, Dict[str, Any]]:
    """Build each root, let ``boundary(root, facts)`` warm up and return the counted call; compare."""
    counted, answers = {}, {}
    for k in (K_SMALL, K_LARGE):
        root = tmp_path / f"k{k:03d}" / "data"
        root.mkdir(parents=True)
        monkeypatch.setenv("OUROBOROS_DATA_DIR", str(root))
        call = boundary(root, build(root, k))
        with CostMeter(root) as meter:
            answers[k] = tagged(TAG, call)
        counted[k] = meter.snapshot(TAG)
    breaches = contract_breaches(counted[K_SMALL]["counts"], counted[K_LARGE]["counts"], K_LARGE)
    growing = sorted(((source, amount - counted[K_SMALL]["callers"].get(source, 0))
                      for source, amount in counted[K_LARGE]["callers"].items()
                      if amount > counted[K_SMALL]["callers"].get(source, 0)), key=lambda item: -item[1])[:8]
    assert not breaches, f"grows with unrelated history (k={K_SMALL} -> k={K_LARGE}): {breaches}; growing: {growing}"
    return answers


# ---- send_message: the terminal answer's receipt capture over k-scaled evidence packs ------------

PACKS_PER_K = 3


def _packed_history(root, k):
    """``PACKS_PER_K`` settled tasks per unit, packed by the real packer (sidecars, packs, index)."""
    from ouroboros import evidence_packer
    from tests.test_evidence_packs import _task

    for unit in range(k):
        for index in range(PACKS_PER_K):
            _task(root, f"hist-{unit}-{index}", blobs=2)
    assert evidence_packer.run_pass(root)["faults"] == 0
    return {}


def _sender(root, monkeypatch):
    """The supervisor's send seam with a local bridge; frames are what the owner's chat received."""
    from ouroboros import utils
    from supervisor import events_chat_delivery, message_bus
    from supervisor.event_observation import ObservedEventQueue
    from tests.test_dialogue_retry import bridge, seed

    seed(root, monkeypatch)
    frames = bridge(root, monkeypatch)
    queue = ObservedEventQueue()
    monkeypatch.setattr(events_chat_delivery, "_DELIVERED_MESSAGE_IDS", deque(maxlen=256))
    monkeypatch.setattr(events_chat_delivery, "_ACTIVE_DELIVERIES", set())
    monkeypatch.setattr(events_chat_delivery, "_DEFERRED_DELIVERIES", set())
    monkeypatch.setattr("supervisor.workers.get_event_q", lambda **_kw: queue)
    ctx = SimpleNamespace(DRIVE_ROOT=root, RUNNING={}, EVENT_Q=queue, append_jsonl=utils.append_jsonl,
                          send_with_budget=message_bus.send_with_budget)
    return ctx, frames


def _owed_answer(root, task_id):
    from ouroboros.task_results import write_task_result
    from supervisor import terminal_delivery

    write_task_result(root, task_id, "running", chat_id=1, root_task_id=task_id)
    text = f"The answer of {task_id}."
    event = {"type": "send_message", "chat_id": 1, "task_id": task_id, "text": text,
             "delivery_id": terminal_delivery.delivery_id_for(task_id, text)}
    assert terminal_delivery.register_pending_delivery(root, event)
    return event


@pytest.mark.parametrize("index", ["validated", "stale", "contended", "damaged"])
def test_send_message_receipt_capture_is_flat_across_evidence_packs(tmp_path, monkeypatch, index):
    """The delivering task names its own handle, so the capture reads that task's own sidecars.

    ``validated``: the pack index was checked by this process (the quiet case even before the
    fix); ``stale``: the packer wrote the index since (re-validation is a whole-index
    ``quick_check``); ``contended``: the packer holds the index lock past the send's
    acquisition slice (the 22.10 stalls: every sidecar opened and parsed); ``damaged``: the
    cache must be rebuilt from every sidecar. The answer still reaches the chat and keeps its
    retained receipt on both sizes."""
    from ouroboros import evidence_packs, store
    from supervisor import events_chat_delivery

    def boundary(root, _facts):
        ctx, frames = _sender(root, monkeypatch)
        assert events_chat_delivery._handle_send_message(_owed_answer(root, "warm-up"), ctx)
        event = _owed_answer(root, "turn")
        holder = None
        if index == "stale":
            evidence_packs._VALIDATED.clear()
        elif index == "damaged":
            (evidence_packs.packs_dir(root) / evidence_packs.INDEX_NAME).write_bytes(b"not a database")
            evidence_packs._VALIDATED.clear()
        elif index == "contended":
            held, release = threading.Event(), threading.Event()

            def hold():
                with store.name_lock(root, evidence_packs.INDEX_LOCK_NAME, timeout_sec=5):
                    held.set()
                    release.wait(30)

            holder = threading.Thread(target=hold, name="packer-holds-index")
            holder.start()
            assert held.wait(5)

        def send():
            try:
                sent = events_chat_delivery._handle_send_message(event, ctx)
            finally:
                if holder is not None:
                    release.set()
                    holder.join(10)
            registry = json.loads((root / "state" / "terminal_deliveries.json").read_text(encoding="utf-8"))
            receipt = registry["receipts"][event["delivery_id"]]
            return (sent, frames[-1]["delivery_id"] == event["delivery_id"],
                    receipt["source_ref"]["path"].startswith("source_handles/context_checkpoints/"))
        return send

    answers = _flat(tmp_path, monkeypatch, _packed_history, boundary)
    assert answers[K_SMALL] == answers[K_LARGE] == (True, True, True)


def _spy_sidecars(monkeypatch):
    from ouroboros import evidence_packs

    decoded, real = [], evidence_packs.read_sidecar

    def read(path, **kwargs):
        decoded.append(path.name)
        return real(path, **kwargs)

    monkeypatch.setattr(evidence_packs, "read_sidecar", read)
    return decoded


def test_a_task_handle_is_answered_by_its_own_sidecars_only(tmp_path, monkeypatch):
    """Another task's pack never joins the answer: an unreadable unrelated sidecar neither blocks a
    lookup nor turns an absence into an error, a dotted task id is told apart by the sidecar's own
    ``task_id``, and this task's own unreadable sidecar stays an explicit error."""
    from ouroboros import evidence_packer, evidence_packs as packs
    from tests.test_evidence_packs import _task

    monkeypatch.setenv("OUROBOROS_DATA_DIR", str(tmp_path))
    handles = {task: _task(tmp_path, task, blobs=1, handle=f"# focus {task}\n".encode())[1]
               for task in ("a", "a.2", "b")}
    assert evidence_packer.run_pass(tmp_path)["faults"] == 0
    (packs.packs_dir(tmp_path) / "b.members.json").write_text("{", encoding="utf-8")
    packs._VALIDATED.clear()  # nothing validated the cache in this process
    decoded = _spy_sidecars(monkeypatch)
    assert packs.handle_bytes(tmp_path, "a", handles["a"]["path"]) == b"# focus a\n"
    assert packs.handle_info(tmp_path, "a", handles["a"]["path"].replace("focus_source", "absent")) is None
    assert packs.packed_handle_names(tmp_path, "a") == [handles["a"]["path"].rsplit("/", 1)[-1]]
    assert packs.handle_bytes(tmp_path, "a.2", handles["a.2"]["path"]) == b"# focus a.2\n"
    assert set(decoded) <= {"a.members.json", "a.2.members.json"}, decoded  # never b's, never another task's
    (packs.packs_dir(tmp_path) / "a.members.json").write_text("{", encoding="utf-8")
    (packs.packs_dir(tmp_path) / packs.INDEX_NAME).unlink()  # no cache that could still vouch for it
    with pytest.raises(packs.SidecarCorrupt, match="evidence_corrupt"):
        packs.handle_bytes(tmp_path, "a", handles["a"]["path"])


@pytest.mark.parametrize("index", ["valid", "absent"])
def test_a_valid_index_keeps_a_placement_whose_own_sidecar_was_damaged(tmp_path, monkeypatch, index):
    """The packer's index outlives a damaged sidecar even when this process never validated it: only
    then is the existing cache checked (never rebuilt). Without a cache the damage stays explicit."""
    from ouroboros import evidence_packer, evidence_packs as packs
    from tests.test_evidence_packs import _task

    monkeypatch.setenv("OUROBOROS_DATA_DIR", str(tmp_path))
    _refs, handle = _task(tmp_path, "kept", blobs=1)
    assert evidence_packer.run_pass(tmp_path)["faults"] == 0
    packs._VALIDATED.clear()
    (packs.packs_dir(tmp_path) / "kept.members.json").write_text("{", encoding="utf-8")
    if index == "absent":
        (packs.packs_dir(tmp_path) / packs.INDEX_NAME).unlink()
        with pytest.raises(packs.SidecarCorrupt):
            packs.handle_bytes(tmp_path, "kept", handle["path"])
        assert not (packs.packs_dir(tmp_path) / packs.INDEX_NAME).exists()  # the read rebuilt nothing
    else:
        assert packs.handle_bytes(tmp_path, "kept", handle["path"]).startswith(b"# focus")
        assert packs.handle_info(tmp_path, "kept", handle["path"]) == {
            "size": handle["size"], "sha256": handle["sha256"], "loose": False}
