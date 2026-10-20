"""New GitHub operations use the same task, principal and network authority."""
from dataclasses import replace

import pytest

from ouroboros.tools.registry import ToolContext, ToolRegistry

READERS = ("get_github_run_log", "list_github_run_artifacts", "download_github_artifact")
WRITERS = ("create_github_pr", "update_github_pr", "set_github_pr_ready")


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr("ouroboros.safety.check_safety", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr("ouroboros.tools.github.github_cli_configured", lambda: True)
    repo, data = tmp_path / "repo", tmp_path / "data"
    repo.mkdir()
    data.mkdir()
    reg = ToolRegistry(repo_dir=repo, drive_root=data)
    reg.set_context(ToolContext(repo_dir=repo, drive_root=data))
    seen = []
    for name in READERS + WRITERS:
        def handler(ctx, _name=name, **args):
            seen.append((_name, args))
            return "OK: reached permitted handler"
        reg._entries[name] = replace(reg._entries[name], handler=handler)
    return reg, seen


@pytest.mark.parametrize("name", READERS + WRITERS)
def test_no_network_blocks_before_handler_and_network_allows(registry, name):
    reg, seen = registry
    reg._ctx.task_contract = {"allowed_resources": {"network": False}}
    denied = reg.execute_result(name, {"repo": "owner/repo"})
    assert denied.status == "blocked" and seen == []
    reg._ctx.task_contract = {"allowed_resources": {"network": True}}
    assert reg.execute_result(name, {"repo": "owner/repo"}).status == "ok"
    assert seen == [(name, {"repo": "owner/repo"})]


def test_callable_catalog_agrees_with_github_network_dispatch(registry, monkeypatch):
    from ouroboros.tools.registry_guards import _GITHUB_TOKEN_TOOLS
    from ouroboros.tools.tool_discovery import list_available_tools

    reg, seen = registry
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    names = READERS + WRITERS + ("get_github_pr", "list_github_issues")
    registered_family = set(_GITHUB_TOKEN_TOOLS) & set(reg.available_tools())
    assert set(names) <= registered_family
    for name in names:
        if name not in READERS + WRITERS:
            reg._entries[name] = replace(
                reg._entries[name],
                handler=lambda ctx, _name=name, **args: seen.append((_name, args)) or "OK",
            )
    for network, expected_status in ((False, "blocked"), (True, "ok")):
        reg._ctx.task_contract = {"allowed_resources": {"network": network}}
        catalog = list_available_tools(reg, reg._ctx, None, namespace="builtin")
        rows = {row["name"] for row in reg.callable_rows("builtin")}
        for name in registered_family:
            assert (name in rows) is network
            assert (f"- {name} [" in catalog) is network
        for name in names:
            before = len(seen)
            result = reg.execute_result(name, {"repo": "owner/repo"})
            assert result.status == expected_status, (name, result.text)
            assert len(seen) == before + int(network)


@pytest.mark.parametrize("level", ["observe", "act", "full"])
def test_observe_reads_only_and_other_levels_retain_writes(registry, level):
    from ouroboros.consciousness_authority import apply_consciousness_authority
    reg, seen = registry
    task = apply_consciousness_authority({"id": "wake", "metadata": {
        "initiator": "consciousness", "consciousness_autonomy": level,
    }})
    reg._ctx.task_metadata = task["metadata"]
    for name in READERS + WRITERS:
        result = reg.execute_result(name, {"repo": "owner/repo"})
        assert result.status == ("blocked" if level == "observe" and name in WRITERS else "ok"), result.text
    assert {name for name, _ in seen} == set(READERS if level == "observe" else READERS + WRITERS)


def test_readonly_profile_cannot_get_writers_even_with_network(registry):
    from ouroboros.contracts.task_constraint import TaskConstraint
    reg, seen = registry
    reg._ctx.task_constraint = TaskConstraint(mode="local_readonly_subagent", allow_enable=False)
    for name in READERS:
        assert reg.get_schema_by_name(name)
        assert reg.execute_result(name, {"repo": "owner/repo"}).status == "ok"
    for name in WRITERS:
        assert reg.get_schema_by_name(name) is None
        assert reg.execute_result(name, {"repo": "owner/repo"}).status == "blocked"
    assert {name for name, _ in seen} == set(READERS)


def test_presence_grants_only_one_exact_operation_and_binds_repository(registry):
    from ouroboros.presence_authority import PresenceCapabilityCeiling, PresenceToolGrant, presence_ceiling_payload
    from ouroboros.presence_capabilities import PresenceArgumentBinding
    reg, seen = registry
    ceiling = PresenceCapabilityCeiling(
        skill_name="reader", skill_content_hash="a" * 64, profile_fingerprint="b" * 64,
        state_fingerprint="c" * 64, selection_fingerprint="d" * 64,
        model_slot="main", inline_max_rounds=3,
        tool_grants=(PresenceToolGrant("get_github_run_log", (
            PresenceArgumentBinding(("repo",), "static", static_value="owner/selected"),)),),
        resource_grants=(), digest="0" * 64)
    reg._ctx.task_contract = {"capability_ceiling": presence_ceiling_payload(ceiling)}
    result = reg.execute_result("get_github_run_log", {"repo": "other/repo", "run_id": 1})
    assert result.status == "ok", result.text
    assert seen == [("get_github_run_log", {"repo": "owner/selected", "run_id": 1})]
    for name in WRITERS + READERS[1:]:
        assert reg.execute_result(name, {"repo": "owner/selected"}).status == "blocked"
    assert len(seen) == 1
