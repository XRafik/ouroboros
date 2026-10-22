"""Registered regressions for retained targets and descriptor eligibility."""
import ast
import json

import pytest

from ouroboros import mcp_client
from tests.test_canonical_runtime_reads import actor, world as _world

world = _world


@pytest.mark.parametrize("profile", ["root", "local_readonly_subagent", "acting_subagent"])
def test_directory_recipe_keeps_canonical_target(world, profile):
    _, registry = actor(world, profile)
    for base, name in ((world.drive_root, "canonical-only.txt"), (world.fork, "execution-only.txt")):
        (base / "only").mkdir()
        (base / "only" / name).write_text("marker")
    response = registry.execute_result("read_file", {"path": str(world.drive_root / "only")})
    recipe = next(line.strip() for line in response.text.splitlines() if line.strip().startswith("list_files("))
    call = ast.parse(recipe, mode="eval").body
    args = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
    listed = registry.execute_result("list_files", args)
    assert listed.status == "ok" and "canonical-only.txt" in listed.text
    assert "execution-only.txt" not in listed.text


@pytest.mark.parametrize("keyword", ["default", "const", "enum", "examples", "x-extension"])
def test_mcp_secret_literal_withholds_only_affected_descriptor(monkeypatch, keyword):
    token = "synthetic-schema-literal-secret"
    literal = {"description": token, "title": "ordinary"}
    value = [literal] if keyword in {"enum", "examples"} else literal
    async def listing(cfg, timeout):
        return [
            {"name": "bad", "input_schema": {"type": "object", keyword: value}},
            {"name": "good", "description": token, "input_schema": {
                "type": "object", "properties": {"x": {"default": {"description": "literal"}}}}},
        ]
    manager = mcp_client.MCPManager()
    manager._async_list_tools = listing
    manager.reconfigure({"MCP_ENABLED": True, "MCP_SERVERS": [{
        "id": "secret", "enabled": True, "transport": "streamable_http",
        "url": "https://example.test/mcp", "auth_token": token, "allowed_tools": []}]})
    result = manager.refresh_server("secret")
    assert token not in json.dumps(result)
    assert "MCP_SCHEMA_LITERAL_SECRET" in json.dumps(manager.status_payload())
    rows = manager.list_tools_for_registry()
    assert len(rows) == 1 and rows[0]["name"].endswith("__good")
    assert rows[0]["schema"]["properties"]["x"]["default"] == {"description": "literal"}
    assert token not in json.dumps(rows)
    assert manager.resolve_tool_name("mcp_secret__bad").status != "callable"


def test_all_schema_readers_agree_on_network_gate(tmp_path, monkeypatch):
    from ouroboros.tools.registry import ToolContext, ToolRegistry
    from ouroboros.tools.tool_discovery import enable_tools
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-token")
    reg = ToolRegistry(tmp_path / "repo", tmp_path / "data")
    reg.set_context(ToolContext(repo_dir=tmp_path / "repo", drive_root=tmp_path / "data", task_id="actor"))
    for allowed in (False, True):
        reg._ctx.task_contract = {"allowed_resources": {"network": allowed}}
        name = "github_read"
        for core_only in (False, True):
            assert (name in {row["function"]["name"] for row in reg.schemas(core_only=core_only)}) is allowed
        assert (reg.get_schema_by_name(name) is not None) is allowed
        assert (reg.policy_hidden_reason(name) is None) is allowed
        answer = enable_tools(reg, reg._ctx, name, [])
        assert ("resource_blocked" in answer) is not allowed
