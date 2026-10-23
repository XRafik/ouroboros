"""All update doors observe the effective Git lock before they stop any work."""

import contextlib
import json
import pathlib
from types import SimpleNamespace

import pytest

from ouroboros.gateway import control
from supervisor import git_ops, git_ops_reset, workers
from tests.test_git_lock_owners import _git, _repo, _live_writer


@pytest.mark.parametrize("topology", ["checkout", "linked-worktree", "alternate-index"])
@pytest.mark.parametrize("holder", ["orphan", "live"])
@pytest.mark.parametrize("door", ["smart", "replace", "ui_rollback", "vcs_rollback"])
def test_lock_refusal_precedes_every_stop(tmp_path, monkeypatch, topology, holder, door):
    repo = _repo(tmp_path)
    if topology == "linked-worktree":
        linked = tmp_path / "linked"
        _git(repo, "worktree", "add", "-qb", "linked", str(linked))
        repo = linked
    elif topology == "alternate-index":
        alternate = tmp_path / "custom-index"
        alternate.write_bytes((repo / ".git" / "index").read_bytes())
        monkeypatch.setenv("GIT_INDEX_FILE", str(alternate))
    monkeypatch.setattr(git_ops, "REPO_DIR", repo)
    monkeypatch.setattr(git_ops, "DRIVE_ROOT", tmp_path / "data")
    monkeypatch.setattr(workers, "_repo_writer_gate_reason", "")
    stopped = []
    monkeypatch.setattr(control, "_quiesce_repo_writers", lambda reason: stopped.append(reason) or [])
    monkeypatch.setattr(control, "_respawn_workers_after_failed_update", lambda: pytest.fail("nothing stopped"))
    path = pathlib.Path(str(git_ops_reset.effective_index_path()) + ".lock")
    with contextlib.ExitStack() as stack:
        writer = stack.enter_context(_live_writer(repo)) if holder == "live" else None
        if writer is None:
            path.write_bytes(b"orphaned index writer\n")
        before = path.read_bytes(), path.stat().st_ino
        if door in {"ui_rollback", "vcs_rollback"}:
            status, body = control.rollback_through_door("HEAD", door=door,
                request_restart=lambda: pytest.fail("a refusal cannot restart"))
        else:
            apply = control._apply_smart_update_fenced if door == "smart" else control._apply_replace_recovery_fenced
            response = apply(SimpleNamespace(), expected_base_sha="a" * 40, expected_target_sha="b" * 40)
            status, body = response.status_code, json.loads(response.body)
        assert (status, body["reason"], body["outcome"]) == (409, "index_lock_present", "not_applied")
        assert body["index_lock"]["path"] == str(path) and body["index_lock"]["exists"] is True
        assert stopped == [] and workers.repo_writer_admission_closed() == ""
        assert (path.read_bytes(), path.stat().st_ino) == before
        if writer:
            assert writer.finish() == 0, writer.stderr


def test_absent_lock_is_observed_without_creating_one(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(git_ops, "REPO_DIR", repo)
    assert control._index_lock_precondition() is None
    assert not (repo / ".git" / "index.lock").exists()
