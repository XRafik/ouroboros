"""Real Git: observations preserve the index; writers still acquire its lock."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from supervisor import git_ops
from tests.test_git_lock_owners import _git, _repo


def _index(repo):
    path = repo / ".git" / "index"
    stat = path.stat()
    return path.read_bytes(), stat.st_ino, stat.st_mtime_ns


@pytest.mark.parametrize("changed", [False, True], ids=["stat-dirty-same-content", "real-content"])
@pytest.mark.parametrize("reader", ["capture", "bounded", "shell", "attribution", "review", "tool",
                                    "preflight", "checkpoint", "patch", "streamed_patch", "subject", "pr", "drift"])
def test_host_observations_never_write_the_index(tmp_path, monkeypatch, changed, reader):
    from ouroboros import mutation_attribution, utils
    from ouroboros.tools import review_file_pack, shell_effects, vcs_read

    monkeypatch.setattr(vcs_read, "_CONFIG_LOCATIONS", vcs_read._CONFIG_LOCATIONS | {"GIT_TRACE2_EVENT"})
    repo = _repo(tmp_path)
    monkeypatch.setattr(git_ops, "REPO_DIR", repo)
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")  # defeat the test launcher's protective default
    trace = tmp_path / "git-trace.jsonl"
    _git(repo, "config", "trace2.eventTarget", str(trace))
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))
    seed = repo / "seed.txt"
    if changed:
        seed.write_text("different content\n", encoding="utf-8")
    stat = seed.stat()
    os.utime(seed, ns=(stat.st_atime_ns, stat.st_mtime_ns - 10_000_000_000))
    before = _index(repo)
    if reader in {"capture", "bounded"}:
        results = [git_ops.git_capture(["git", *args], timeout=10 if reader == "bounded" else None)
                   for args in (("status", "--porcelain"), ("diff", "--stat"))]
        assert all(row[0] == 0 for row in results)
        output = "".join(row[1] for row in results)
    elif reader == "shell":
        output = "".join(shell_effects._get_changed_files(repo)) + shell_effects._get_diff_stat(repo)
    elif reader == "attribution":
        output = mutation_attribution._run_git(repo, "status", "--porcelain")
    elif reader == "review":
        output = "".join(review_file_pack.list_changed_paths_from_git_status(repo))
    elif reader == "tool":
        output = vcs_read._capture_read_git(repo, ["diff", "--stat"]).stdout.decode("utf-8")
    elif reader == "preflight":
        from ouroboros.workspace_preflight import _git_stdout
        output = _git_stdout(repo, ["git", "status", "--porcelain"], timeout=10)
    elif reader == "checkpoint":
        from ouroboros.coop_checkpoint import _run_git
        output = _run_git(["git", "status", "--porcelain"], repo).stdout
    elif reader in {"patch", "streamed_patch"}:
        from ouroboros.workspace_patch_capture import _git_bytes, _append_git_output
        cmd = ["git", "diff", "--stat"]
        if reader == "patch":
            output = _git_bytes(cmd, repo).decode("utf-8")
        else:
            captured = tmp_path / "captured.diff"
            errors = []
            with captured.open("wb") as stream:
                _append_git_output(cmd, repo, stream, allow_rc={0}, errors=errors, diagnostics=[])
            assert errors == []
            output = captured.read_text(encoding="utf-8")
    elif reader == "subject":
        from ouroboros.tools.review_subject import _git_bytes
        output = _git_bytes(repo, ["diff", "--stat"])[1].decode("utf-8")
    elif reader == "pr":
        from ouroboros.tools.git_pr import _g
        output = _g(["status", "--porcelain"], repo).stdout
    else:
        from ouroboros.delegate_target_drift import _target_drift_evidence
        entry = SimpleNamespace(target_root=repo, baseline_sha=_git(repo, "rev-parse", "HEAD"))
        evidence = _target_drift_evidence(entry)
        assert evidence["checked"], evidence
        output = "".join(evidence["paths"])
    assert ("seed.txt" in output) is changed
    assert _index(repo) == before
    assert not (repo / ".git" / "index.lock").exists()
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert not [row for row in rows if row.get("label") == "do_write_index"]
    # The ordinary tool command seam shares the same convention.
    assert bool(utils.run_cmd(["git", "diff", "--stat"], cwd=repo)) is changed
    assert _index(repo) == before


@pytest.mark.parametrize("command", [("reset", "--hard", "HEAD"), ("checkout", "-B", "other"),
                                   ("commit", "--allow-empty", "-qm", "writer"),
                                   ("merge", "--no-edit", "other")])
def test_writer_locks_remain_mandatory(tmp_path, monkeypatch, command):
    repo = _repo(tmp_path)
    monkeypatch.setattr(git_ops, "REPO_DIR", repo)
    if command[0] == "merge":
        _git(repo, "checkout", "-b", "other")
        (repo / "other.txt").write_text("merge me\n", encoding="utf-8")
        _git(repo, "add", "other.txt")
        _git(repo, "commit", "-qm", "other")
        _git(repo, "checkout", "ouroboros")
    lock = repo / ".git" / "index.lock"
    lock.write_bytes(b"external writer")
    inode = lock.stat().st_ino
    rc, _, error = git_ops.git_capture(["git", *command])
    assert rc != 0 and "index.lock" in error
    assert (lock.read_bytes(), lock.stat().st_ino) == (b"external writer", inode)
    lock.unlink()  # fixture owner releases it
    assert git_ops.git_capture(["git", *command])[0] == 0


def test_observation_does_not_repair_corruption_but_a_writer_can(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(git_ops, "REPO_DIR", repo)
    index = repo / ".git" / "index"
    index.write_bytes(b"broken")
    before = _index(repo)
    assert git_ops.git_capture(["git", "status", "--porcelain"])[0] != 0
    assert _index(repo) == before and not list(index.parent.glob("index.corrupt.*"))
    assert git_ops.git_capture(["git", "reset", "--mixed", "HEAD"], repair_index=True)[0] == 0
    assert _git(repo, "ls-files") == "seed.txt"


def test_read_policy_beats_inherited_config_without_losing_it(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    env = git_ops.host_git_env()
    for key in ("core.autocrlf", "diff.autoRefreshIndex"):
        result = subprocess.run(["git", "config", "--get", key], cwd=repo, env=env,
                                capture_output=True, text=True, check=True)
        assert result.stdout.strip() == "false"
