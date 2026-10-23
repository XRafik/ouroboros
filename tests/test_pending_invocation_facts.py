"""Pending-start inventories use typed open facts; only backfill/replay reads the source."""
import pytest

from ouroboros import delegate_custody as custody, delegate_pending, maintenance, store
from ouroboros import delegate_custody_current as current
from ouroboros.observability import write_blob


def request(root, identity):
    return {"type": custody.START_REQUESTED, "task_id": "owner", "invocation_id": identity,
            "request_ref": write_blob(root, {"prompt": "exact assignment", "model": "original"}, kind="json")}


def test_start_publication_keeps_request_facts_until_start_or_definite_refusal(tmp_path, monkeypatch):
    for identity in ("started", "refused", "uncertain"):
        event = request(tmp_path, identity)
        assert custody.emit(tmp_path, custody.START_REQUESTED, event)
    monkeypatch.setattr(delegate_pending, "request_body", lambda *a: pytest.fail("inventory read history"))
    assert {row["request"]["prompt"] for row in custody.pending_invocations(tmp_path)} == {"exact assignment"}
    assert custody.emit(tmp_path, custody.STARTED, {"invocation_id": "started", "run_id": "run", "task_id": "owner"})
    assert custody.emit(tmp_path, custody.START_FAILED, {"invocation_id": "refused", "definite": True})
    assert custody.emit(tmp_path, custody.START_FAILED, {"invocation_id": "uncertain", "definite": False})
    assert [row["invocation_id"] for row in custody.pending_invocations(tmp_path)] == ["uncertain"]


def test_legacy_backfill_reads_only_open_requests_once_and_preserves_an_unreadable_source(tmp_path, monkeypatch):
    events = [request(tmp_path, identity) for identity in ("open", "closed", "unknown")]
    events[-1]["request_ref"]["sha256"] = "0" * 64
    events.append({"type": custody.STARTED, "invocation_id": "closed", "run_id": "closed"})
    with store.open_store(tmp_path, write=True) as txn:
        current.write_fold(txn, current.fold(events), replace=True)
    original, read = delegate_pending.request_body, []
    def observe(root, row):
        read.append(row["invocation_id"])
        return original(root, row)
    monkeypatch.setattr(delegate_pending, "request_body", observe)
    assert {row["invocation_id"] for row in custody.pending_invocations(tmp_path)} == {"open", "unknown"}
    assert read == []
    assert maintenance.run_job(tmp_path, "pending_invocations")["items"] == 2
    assert sorted(read) == ["open", "unknown"]
    assert maintenance.run_job(tmp_path, "pending_invocations") is None
    rows = {row["invocation_id"]: row for row in custody.pending_invocations(tmp_path)}
    assert rows["open"]["request"]["model"] == "original"
    assert rows["unknown"]["request"] is None and rows["unknown"]["request_ref"]
    assert sorted(read) == ["open", "unknown"]


def test_backfill_cannot_resurrect_a_start_that_wins_during_source_read(tmp_path, monkeypatch):
    with store.open_store(tmp_path, write=True) as txn:
        txn.put_row("custody_open", "invocation:racing", {"request": request(tmp_path, "racing")})
    original = delegate_pending.request_body
    def racing(root, row):
        body = original(root, row)
        custody.emit(root, custody.STARTED, {"invocation_id": "racing", "run_id": "run"})
        return body
    monkeypatch.setattr(delegate_pending, "request_body", racing)
    maintenance.run_job(tmp_path, "pending_invocations")
    assert custody.pending_invocations(tmp_path) == []


def test_backfill_does_not_mark_a_racing_import_done(tmp_path, monkeypatch):
    with store.open_store(tmp_path, write=True) as txn:
        current.write_fold(txn, current.fold([request(tmp_path, "first")]), replace=True)
    original, raced = delegate_pending.request_body, []
    def arriving(root, row):
        if not raced:
            raced.append(True)
            with store.open_store(root, write=True) as txn:
                current.write_fold(txn, current.fold([request(root, "arriving")]), replace=False)
        return original(root, row)
    monkeypatch.setattr(delegate_pending, "request_body", arriving)
    assert maintenance.run_job(tmp_path, "pending_invocations")["state"] == "pending"
    assert maintenance.run_job(tmp_path, "pending_invocations")["state"] == "done"
    assert {row["invocation_id"] for row in custody.pending_invocations(tmp_path)} == {"first", "arriving"}
