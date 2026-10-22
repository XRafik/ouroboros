"""Retired action restrictions, bounded history, and configured comparisons."""
import pytest
from tests.test_vcs_read_slice import world as _world, git

world = _world


@pytest.mark.parametrize("retired,action,other", [("vcs_status", "status", "diff"), ("vcs_diff", "diff", "status")])
def test_retired_names_are_unknown_and_saved_disables_withhold_only_their_action(world, retired, action, other):
    registry, ctx, _, _project = world
    assert registry.get_schema_by_name(retired) is None
    assert "Unknown tool" in registry.execute(retired, {})
    ctx.task_contract = {"disabled_tools": [retired]}
    blocked = registry.execute_result("vcs_read", {"action": action})
    assert blocked.code == "RESOURCE_CONSTRAINT_BLOCKED"
    assert registry.execute_result("vcs_read", {"action": other}).status == "ok"
    ctx.task_contract = {"disabled_tools": ["vcs_read"]}
    assert registry.execute_result("vcs_read", {"action": other}).code == "RESOURCE_CONSTRAINT_BLOCKED"
    ctx.task_contract = {}
    assert registry.execute_result("vcs_read", {"action": action}).status == "ok"
    from tests.test_preflight_recovery_authority import _presence_contract
    ctx.task_contract = _presence_contract(retired)
    assert registry.get_schema_by_name("vcs_read") is None


@pytest.mark.parametrize("repository", [None, "."])
def test_status_diff_keep_clean_filter_comparison(world, repository):
    registry, _, _, project = world
    (project / ".gitattributes").write_text("note.txt filter=normalize\n")
    git(project, "config", "filter.normalize.clean", "sed s/WORKTREE/CANONICAL/g")
    (project / "note.txt").write_text("WORKTREE\n")
    git(project, "add", ".gitattributes", "note.txt")
    git(project, "commit", "-qm", "normalized")
    # Force Git to compare bytes, rather than trusting a cached stat.
    (project / "note.txt").write_text("WORKTREE\n")
    args = {} if repository is None else {"repository": repository}
    for action in ("status", "diff"):
        result = registry.execute_result("vcs_read", {"action": action, "path": "note.txt", **args})
        assert result.status == "ok", result.text
        assert result.text.startswith("VCS target:"), result.text
    (project / "note.txt").write_text("changed WORKTREE\n")
    difference = registry.execute_result("vcs_read", {"action": "diff", "path": "note.txt", **args})
    assert "+changed CANONICAL" in difference.text


def test_history_capture_is_physically_bounded_and_discloses_narrowing(world, monkeypatch):
    from ouroboros.tools import vcs_read
    registry, _, _, project = world
    (project / "large.txt").write_text("x" * 4096)
    git(project, "add", "large.txt")
    git(project, "commit", "-qm", "large")
    monkeypatch.setattr(vcs_read, "_CAPTURE_BYTES", 256)
    captured = vcs_read._capture_read_git(project, ["show", "HEAD:large.txt"])
    assert len(captured.stdout) == 256 and captured.stdout_omitted == 3840
    result = registry.execute_result("vcs_read", {"action": "file", "path": "large.txt"})
    assert result.status == "ok" and "3840 bytes omitted" in result.text
    assert "max_count (log), ref, or path" in result.text
