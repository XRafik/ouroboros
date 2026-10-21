"""Every settlement writer merges against the locked current per-seat record."""
import concurrent.futures
import copy
import threading

import pytest

from ouroboros import review_ledger as ledger
from tests.test_review_ledger import _facts, _raw, BOTH


def _record(root):
    raws = [_raw(seat, seat, "in_flight", parts=BOTH, operation_id=seat,
                 operation_state="in_flight", late_result_pending=True) for seat in ("a", "b")]
    return ledger.write_record(root, ledger.build_commit_gate_record(_facts(raws), drive_root=root))


def test_concurrent_collectors_keep_both_answers_cost_and_author_decision(tmp_path, monkeypatch):
    record = _record(tmp_path)
    ledger.note_author_decision(tmp_path, record["record_id"], {"disposition": "deferred", "rationale": "wait"})
    original = ledger.revise_record
    barrier = threading.Barrier(2)

    def after_snapshot(*args, **kwargs):
        barrier.wait(timeout=10)  # both callers read the old pending revision
        return original(*args, **kwargs)
    monkeypatch.setattr(ledger, "revise_record", after_snapshot)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(ledger.settle_from_collected, tmp_path, record["record_id"],
                    [_raw(seat, seat, parts=BOTH, operation_id=seat)]) for seat in ("a", "b")]
        for future in futures:
            future.result()
    settled = ledger.load_record(tmp_path, record["record_id"])
    assert settled["state"] == "settled" and settled["verdict"]["aggregate"] == "PASS"
    assert settled["cost"]["usd"] == .02
    assert settled["author_decision"]["disposition"] == "deferred"
    assert {row["seat_id"] for row in settled["rows"] if row["status"] == "responded"} == {"a", "b"}


def test_stale_writer_cannot_replace_answer_or_provenance(tmp_path):
    original = _record(tmp_path)
    fresh = ledger.settle_from_collected(tmp_path, original["record_id"], [_raw("a", "a", parts=BOTH, operation_id="a")])
    stale = copy.deepcopy(original)
    stale["subject"]["tree_sha"] = "different"
    merged = ledger.revise_record(tmp_path, original["record_id"], lambda now: ledger.settle_pending_payload(now, stale))
    assert merged["rows"][0]["status"] == "responded"
    assert merged["subject"] == fresh["subject"]
    assert merged["rows"][1]["status"] == "in_flight"
    # A genuinely new answer to the still-open seat is accepted.
    settled = ledger.settle_from_collected(tmp_path, original["record_id"], [_raw("b", "b", parts=BOTH, operation_id="b")])
    assert settled["verdict"]["aggregate"] == "PASS"


def test_additional_pending_does_not_hold_counted_pass(tmp_path):
    record = _record(tmp_path)
    ledger.revise_record(tmp_path, record["record_id"],
                         lambda row: {**row, "rows": [row["rows"][0], {**row["rows"][1], "additional": True}]})
    settled = ledger.settle_from_collected(tmp_path, record["record_id"], [_raw("a", "a", parts=BOTH, operation_id="a")])
    assert settled["state"] == "pending" and settled["verdict"]["aggregate"] == "PASS"
    # The same open seat counted in a fresh record keeps the verdict pending.
    other = _record(tmp_path)
    pending = ledger.settle_from_collected(tmp_path, other["record_id"], [_raw("a", "a", parts=BOTH, operation_id="a")])
    assert pending["verdict"]["aggregate"] != "PASS"


@pytest.mark.parametrize("operation", ["a", "other-producer"])
def test_collected_answer_must_belong_to_the_recorded_operation(tmp_path, operation):
    record = _record(tmp_path)
    settled = ledger.settle_from_collected(tmp_path, record["record_id"],
                                           [_raw("a", "a", parts=BOTH, operation_id=operation)])
    assert settled["rows"][0]["operation_id"] == "a"
    assert (settled["rows"][0]["status"] == "responded") == (operation == "a")


def test_findings_merge_by_key_and_a_fresh_gate_block_is_kept(tmp_path):
    original = _record(tmp_path)
    complete = ledger.settle_from_collected(tmp_path, original["record_id"],
                                             [_raw(seat, seat, parts=BOTH) for seat in ("a", "b")])
    original["verdict"]["advisory_findings"] = [{"seat_id": "a", "part": "change", "item": "issue", "reason": "old"}]
    complete["verdict"].update(reason="gate_block:binding_mismatch", aggregate="NOT_PERFORMED",
        advisory_findings=[{"seat_id": "a", "part": "change", "item": "issue", "reason": "new"}])
    merged = ledger.settle_pending_payload(original, complete)
    assert len(merged["verdict"]["advisory_findings"]) == 1
    assert merged["verdict"]["reason"] == "gate_block:binding_mismatch"
    complete["verdict"]["reason"] = "pass"
    assert ledger.settle_pending_payload(original, complete)["verdict"]["aggregate"] == "PASS"


