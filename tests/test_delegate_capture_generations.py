"""An unchanged partial receipt is debt, not permission for another filesystem pass.

Drive the real tick, keep its driver alive but parked, and join every submitted future.
Count source scandirs and copies, including worker work; a per-tick source lexists or
witness walk would violate this law even if the saved summary were never decoded.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat

import pytest

from ouroboros import delegate_collection as body, delegate_custody as c, delegate_custody_current as current
from ouroboros import delegate_named_evidence as named, review_checking as checking
from ouroboros.delegate_capture_attempt import collection_due
from tests.test_delegate_body_collection import terminal
from tests.test_delegate_collection_recovery import driven_runtime  # noqa: F401
from tests.test_recovered_capture import EVIDENCE, prepared


def _prepared(root):
    material = root.with_name(root.name + "-material")
    material.mkdir()
    return prepared(material, root, "ordinary")


def _captured(tmp_path, monkeypatch, *, partial=False):
    entry, area, _ = _prepared(tmp_path)
    output = area / checking.EVIDENCE_DIRNAME / "result.bin"
    output.chmod(0o444)
    if partial:
        (output.parent / "gap").symlink_to(output)
    result = body.collect_terminal(tmp_path, entry.run_id, detail=terminal(entry.run_id))
    assert result["workspace_capture"]["named_evidence"]["status"] == ("partial" if partial else "retained")
    return current.run(tmp_path, entry.run_id), area


def test_clock_advanced_partial_is_quiet_but_changed_terminal_and_explicit_capture_work(
        tmp_path, monkeypatch, driven_runtime):  # noqa: F811
    runtime, clock, tick = driven_runtime
    entry, area = _captured(tmp_path, monkeypatch, partial=True)
    assert current.collection_pending(entry) and not collection_due(entry, generation=runtime.runtime_id)
    copies, walks, submissions = [], [], []
    copy, scan, submit = shutil.copyfileobj, os.scandir, runtime.collectors.submit
    def counted_copy(*args, **kwargs):
        copies.append(True)
        return copy(*args, **kwargs)
    def counted_scan(path):
        if str(path).startswith(str(area)):
            walks.append(str(path))
        return scan(path)
    def submitted(*args, **kwargs):
        submissions.append(args)
        return submit(*args, **kwargs)
    monkeypatch.setattr(shutil, "copyfileobj", counted_copy)
    monkeypatch.setattr(os, "scandir", counted_scan)
    monkeypatch.setattr(runtime.collectors, "submit", submitted)
    for moment in (100, 10000):
        clock[0] = moment
        tick()
    assert not submissions and not walks and not copies
    first = body.saved_named_evidence(tmp_path, entry)[0]
    first_bytes = first.read_bytes()
    assert body.observe_run(tmp_path, entry, terminal(entry.run_id, "changed source", seq=8))
    tick()
    assert len(submissions) == 1 and walks and copies
    assert first.read_bytes() == first_bytes
    walks.clear(); copies.clear(); submissions.clear()
    runtime.request(entry.run_id)
    tick()
    assert len(submissions) == 1 and walks and copies
    walks.clear(); copies.clear(); submissions.clear()
    clock[0] += 10000
    tick()
    assert not submissions and not walks and not copies


@pytest.mark.parametrize("destination", ["readonly", "hardlink", "symlink", "parent_symlink"])
def test_changed_evidence_never_writes_through_old_destinations(tmp_path, monkeypatch, destination):
    entry, area = _captured(tmp_path, monkeypatch)
    old_path, old = body.saved_named_evidence(tmp_path, entry)
    old_file = old_path.parent / "files" / checking.EVIDENCE_DIRNAME / "result.bin"
    old_bytes = old_path.read_bytes()
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "result.bin"
    victim.write_bytes(EVIDENCE)
    if destination == "readonly":
        old_file.chmod(0o444)
    elif destination == "hardlink":
        old_file.unlink()
        os.link(victim, old_file)
    elif destination == "symlink":
        old_file.unlink()
        old_file.symlink_to(victim)
    else:
        old_file.unlink()
        old_file.parent.rmdir()
        old_file.parent.symlink_to(outside, target_is_directory=True)
    before = victim.stat()
    source = area / checking.EVIDENCE_DIRNAME / "result.bin"
    source.unlink()
    source.write_bytes(b"new content")
    with monkeypatch.context() as patch:
        patch.setattr(os, "chmod", lambda *a, **k: pytest.fail("capture must not chmod"))
        latest = named.run_named_evidence(tmp_path, entry)
    assert latest["status"] == "retained" and latest["evidence_dir"] != old["evidence_dir"]
    assert old_path.read_bytes() == old_bytes and old_file.read_bytes() == EVIDENCE
    assert victim.read_bytes() == EVIDENCE and victim.stat().st_ino == before.st_ino
    assert stat.S_IMODE(victim.stat().st_mode) == stat.S_IMODE(before.st_mode)
    assert (pathlib.Path(latest["evidence_dir"]) / "files" / checking.EVIDENCE_DIRNAME / "result.bin").read_bytes() == b"new content"
    # Reuse is quiet, and the published manifest preserves the source's mode.
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "copyfileobj", lambda *a, **k: pytest.fail("unchanged evidence copied"))
        assert named.run_named_evidence(tmp_path, entry) == latest


def test_partial_investigation_reuses_its_receipt_and_changed_input_finishes(tmp_path, monkeypatch):
    from tests.test_investigation_custody import _real_investigation
    from ouroboros.tools.delegate_integration import capture_terminal_patch_for_drive

    _, drive, entry, area, _ = _real_investigation(tmp_path, monkeypatch)
    link = area / checking.EVIDENCE_DIRNAME / "unretained-link"
    link.symlink_to(area / "tracked.txt")
    first = capture_terminal_patch_for_drive(drive, entry)["named_evidence"]
    assert first["status"] == "partial" and area.is_dir()
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "copyfileobj", lambda *a, **k: pytest.fail("partial receipt copied again"))
        assert capture_terminal_patch_for_drive(drive, entry)["named_evidence"] == first
    link.unlink()
    result = capture_terminal_patch_for_drive(drive, entry)
    assert result["disposition"] == c.EVIDENCE_RETAINED and not area.exists()
    assert json.loads((pathlib.Path(first["evidence_dir"]) / "summary.json").read_text(encoding="utf-8")) == first


@pytest.mark.parametrize("damage", ["missing", "unreadable"])
def test_a_missing_or_unreadable_receipt_is_a_new_fact(tmp_path, monkeypatch, damage, driven_runtime):  # noqa: F811
    runtime, clock, tick = driven_runtime
    entry, area = _captured(tmp_path, monkeypatch)
    receipt, _ = body.saved_named_evidence(tmp_path, entry)
    if damage == "missing":
        receipt.unlink()
    else:
        receipt.write_text("{broken", encoding="utf-8")
    assert not body.saved_named_evidence(tmp_path, entry)[1]
    assert collection_due(current.run(tmp_path, entry.run_id), generation=runtime.runtime_id)
    tick()
    fresh = current.run(tmp_path, entry.run_id)
    assert body.saved_named_evidence(tmp_path, fresh)[1]["status"] == "retained"
    assert not collection_due(fresh, generation=runtime.runtime_id)
    assert area.is_dir() and not fresh.patch_disposed


def test_plain_result_reads_do_not_request_recapture(tmp_path, monkeypatch, driven_runtime):  # noqa: F811
    from ouroboros.tools.delegate_terminal_evidence import collect_and_deliver_terminal, retained_terminal_result
    from ouroboros.tools.registry import ToolContext

    runtime, _, tick = driven_runtime
    entry, _ = _captured(tmp_path, monkeypatch, partial=True)
    ctx = ToolContext(repo_dir=tmp_path, drive_root=tmp_path, task_id=entry.task_id)
    with monkeypatch.context() as patch:
        patch.setattr(runtime, "request", lambda *a: pytest.fail("reading is not an explicit recapture"))
        for read in (lambda: retained_terminal_result(ctx, entry.run_id),
                     lambda: collect_and_deliver_terminal(ctx, entry.run_id, terminal(entry.run_id), body._shape(entry), entry, None)):
            assert read()["workspace_capture"]["named_evidence"]["status"] == "partial"
    old = body.saved_named_evidence(tmp_path, entry)[0]
    runtime.request(entry.run_id)
    tick()
    assert body.saved_named_evidence(tmp_path, current.run(tmp_path, entry.run_id))[0] != old


def test_transient_capture_retries_once_in_the_next_generation(tmp_path, monkeypatch):
    entry, area, _ = _prepared(tmp_path)
    copy = shutil.copyfileobj
    monkeypatch.setattr(shutil, "copyfileobj", lambda *a, **k: (_ for _ in ()).throw(PermissionError("locked file")))
    first = body.collect_terminal(tmp_path, entry.run_id, detail=terminal(entry.run_id), generation="one")
    assert first["workspace_capture"]["named_evidence"]["status"] == "capture_failed"
    fresh = current.run(tmp_path, entry.run_id)
    assert not collection_due(fresh, generation="one") and collection_due(fresh, generation="two")
    monkeypatch.setattr(shutil, "copyfileobj", copy)
    body.collect_terminal(tmp_path, entry.run_id, generation="two")
    fresh = current.run(tmp_path, entry.run_id)
    assert fresh.named_evidence["status"] == "retained" and not current.collection_pending(fresh)
    assert not collection_due(fresh, generation="three") and area.is_dir()


def test_unpublished_staging_has_a_remover_but_published_receipts_survive(tmp_path, monkeypatch):
    entry, _ = _captured(tmp_path, monkeypatch)
    receipt, _ = body.saved_named_evidence(tmp_path, entry)
    abandoned = receipt.parent.parent / ".evidence-interrupted.pending"
    abandoned.mkdir()
    (abandoned / "bytes").write_bytes(b"incomplete")
    named.run_named_evidence(tmp_path, entry, recapture=True)
    assert not abandoned.exists() and receipt.is_file()
