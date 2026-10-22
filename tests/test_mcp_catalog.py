"""Published listing evidence across server, worker, settings and transport failures."""
from __future__ import annotations

import copy
import json
import threading
from unittest.mock import Mock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from ouroboros import config, mcp_catalog, mcp_client, server_boot
from ouroboros.tools.registry import ToolRegistry
from ouroboros.tool_policy import format_capability_omissions


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(mcp_client, "_manager", None)


def settings(**overrides):
    server = {"id": "demo", "enabled": True, "url": "https://example.test/mcp", **overrides}
    return {"MCP_ENABLED": True, "MCP_SERVERS": [server]}


def install_settings(monkeypatch, value):
    config.SETTINGS_PATH.write_text(json.dumps(value))
    monkeypatch.setattr(config, "load_settings", lambda: value)


def listing(*names):
    return [{"name": name, "description": f"Description {name}", "input_schema": {
        "type": "object", "properties": {"word": {"type": "string", "title": "A word"}}}}
            for name in names]


def publisher(value=None, items=None):
    manager = mcp_client.MCPManager()
    manager.reconfigure(value or settings())
    async def list_tools(cfg, timeout):
        return listing("ping") if items is None else items
    manager._async_list_tools = list_tools
    return manager


def fail(manager, message="offline"):
    async def broken(cfg, timeout):
        raise TimeoutError(message)
    manager._async_list_tools = broken
    return manager.refresh_server("demo")


def names(manager):
    return [row["name"] for row in manager.list_tools_for_registry()]


def test_publication_seeds_identical_rows_without_transport(monkeypatch):
    items = listing("Ping!", "next")
    items[0].update(annotations={"readOnlyHint": True}, metadata={"kind": "query"}, discarded=123)
    writer = publisher(items=items)
    assert writer.refresh_server("demo")["published"]
    envelope = json.loads(mcp_catalog.catalog_path("demo").read_text())
    assert envelope["items"][0]["input_schema"] == items[0]["input_schema"]
    assert envelope["items"][0]["annotations"] == items[0]["annotations"]
    assert envelope["items"][0]["metadata"] == items[0]["metadata"]
    assert "discarded" not in envelope["items"][0]
    reader = publisher()
    reader._async_list_tools = Mock(side_effect=AssertionError("worker listed"))
    assert reader.list_tools_for_registry() == writer.list_tools_for_registry()
    reader.reload_catalogs()
    reader._async_list_tools.assert_not_called()
    assert envelope["_schema_version"] == 1
    assert envelope["server_id"] == "demo"


def test_published_annotation_hints_reach_every_process(monkeypatch):
    from ouroboros import tool_effects
    monkeypatch.setattr(tool_effects, "_MCP_ANNOTATIONS", {})
    items = listing("read")
    items[0]["annotations"] = {"readOnlyHint": True, "destructiveHint": False}
    writer = publisher(items=items)
    assert writer.refresh_server("demo")["published"]
    name = mcp_client.make_tool_name("demo", "read")
    tool_effects._MCP_ANNOTATIONS.clear()  # a worker starts without the server's memory
    reader = publisher()
    reader._async_list_tools = Mock(side_effect=AssertionError("worker listed"))
    reader.list_tools_for_registry()
    fact = tool_effects.effect_of(name, is_mcp=True)
    assert fact.annotations == {"readOnlyHint": True, "destructiveHint": False}
    assert fact.effect == "write" and not fact.declared  # hints never grant authority
    async def plain(cfg, timeout):
        return listing("read")
    writer._async_list_tools = plain
    assert writer.refresh_server("demo")["published"]
    tool_effects._MCP_ANNOTATIONS["demo"] = {name: {"readOnlyHint": True}}  # the worker's stale memory
    reader.reload_catalogs()
    assert tool_effects.effect_of(name, is_mcp=True).annotations == {}


def test_failed_relisting_retains_tools_and_discloses_in_task(monkeypatch, tmp_path):
    value = settings()
    install_settings(monkeypatch, value)
    manager = publisher(value)
    assert manager.refresh_server("demo")["published"]
    before = json.loads(mcp_catalog.catalog_path("demo").read_text())
    rows = manager.list_tools_for_registry()
    assert fail(manager)["ok"] is False
    after = json.loads(mcp_catalog.catalog_path("demo").read_text())
    assert after["items"] == before["items"] and after["listed_at"] == before["listed_at"]
    assert after["latest_attempt"]["ok"] is False
    assert manager.list_tools_for_registry() == rows
    monkeypatch.setattr(mcp_client, "_manager", publisher(value))
    registry = ToolRegistry(repo_dir=tmp_path, drive_root=tmp_path / "fork")
    registry.schemas()
    notice = "\n".join(format_capability_omissions(registry.capability_omissions()))
    assert before["listed_at"] in notice and after["latest_attempt"]["at"] in notice
    assert "failed: TimeoutError: offline" in notice
    assert manager.resolve_tool_name("mcp_demo__ping").status == "callable"
    miss = manager.resolve_tool_name("mcp_demo__missing").refusal("mcp_demo__missing")
    assert miss.code == "MCP_CATALOG_UNAVAILABLE" and "unknown" in miss.text
    assert manager.status_payload()["servers"][0]["tool_count"] == 1


def test_first_failure_is_attempt_only_and_worker_never_lists(monkeypatch, tmp_path):
    install_settings(monkeypatch, settings())
    manager = publisher()
    assert not fail(manager)["ok"]
    envelope = json.loads(mcp_catalog.catalog_path("demo").read_text())
    assert envelope["listed_at"] is None and envelope["items"] == []
    reader = publisher()
    reader._async_list_tools = Mock(side_effect=AssertionError("worker discovery"))
    monkeypatch.setattr(mcp_client, "_manager", reader)
    registry = ToolRegistry(repo_dir=tmp_path, drive_root=tmp_path)
    assert not any(row["function"]["name"].startswith("mcp_") for row in registry.schemas())
    notice = "\n".join(format_capability_omissions(registry.capability_omissions()))
    assert "never listed under the current configuration" in notice and "offline" in notice
    reader._async_list_tools.assert_not_called()


@pytest.mark.parametrize("change", ["url", "auth_token", "env_value", "headers"])
def test_identity_change_ignores_file_until_server_event_prunes(change, monkeypatch):
    old = settings(auth_token="synthetic-old")
    if change == "env_value":
        old = settings(transport="stdio", url="", command="server", env_from_settings={"TOKEN": "SAVED"})
        old["SAVED"] = "synthetic-old"
    writer = publisher(old)
    writer.refresh_server("demo")
    path = mcp_catalog.catalog_path("demo")
    same = publisher(old)
    assert names(same)
    new = copy.deepcopy(old)
    if change == "env_value":
        new["SAVED"] = "synthetic-new"
    else:
        new["MCP_SERVERS"][0][change] = {"X-Key": "synthetic-new"} if change == "headers" else (
            "https://other.test/mcp" if change == "url" else "synthetic-new")
    reader = publisher(new)
    assert names(reader) == [] and path.exists()
    monkeypatch.setattr(reader, "refresh_all_background", Mock())
    reader.configuration_changed(new, reason="settings")
    assert not path.exists()


def test_boot_seeds_before_blocked_listing_and_prunes_removed(monkeypatch, tmp_path):
    writer = publisher()
    writer.refresh_server("demo")
    orphan = mcp_catalog.catalog_path("gone")
    orphan.write_text("{}")
    install_settings(monkeypatch, settings())
    manager = mcp_client.get_manager()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    async def blocked(cfg, timeout):
        entered.set()
        assert release.wait(5)
        return listing("ping")
    manager._async_list_tools = blocked
    original = manager.refresh_all
    def walk():
        try:
            return original()
        finally:
            finished.set()
    monkeypatch.setattr(manager, "refresh_all", walk)
    registry = ToolRegistry(repo_dir=tmp_path, drive_root=tmp_path / "fork")
    # Before the MCP boot step, its configure path already seeds the file.
    assert any(row["function"]["name"] == "mcp_demo__ping" for row in registry.schemas())
    server_boot.mcp_startup(settings())
    try:
        assert entered.wait(5) and not orphan.exists()
        assert any(row["function"]["name"] == "mcp_demo__ping" for row in registry.schemas())
    finally:
        release.set()
        assert finished.wait(5)


def test_read_time_allowlist_and_cyber_filter_share_one_file(monkeypatch):
    writer = publisher(items=listing("ping", "other"))
    writer.refresh_server("demo")
    path = mcp_catalog.catalog_path("demo")
    original = path.read_bytes()
    monkeypatch.setattr(mcp_client, "mode_has_unrestricted_agency", lambda _: False)
    reader = publisher(settings(allowed_tools=["ping"]))
    assert names(reader) == ["mcp_demo__ping"]
    assert reader.resolve_tool_name("mcp_demo__other").status == "disallowed"
    monkeypatch.setattr(mcp_client, "mode_has_unrestricted_agency", lambda _: True)
    assert names(reader) == ["mcp_demo__ping", "mcp_demo__other"]
    assert path.read_bytes() == original
    reader.reconfigure(settings(enabled=False))
    assert names(reader) == [] and path.read_bytes() == original


def test_catalog_secret_hygiene_preserves_executable_fields():
    secret = "synthetic-auth-secret"
    text = secret + "x" * 1200
    items = [{"name": "probe", "description": text, "input_schema": {
        "title": text, "properties": {"value": {"description": text, "enum": ["exact"]}}}}]
    writer = publisher(settings(auth_token=secret), items)
    writer.refresh_server("demo")
    raw = mcp_catalog.catalog_path("demo").read_text()
    assert secret not in raw and "x" * 1200 in raw
    data = json.loads(raw)
    assert data["items"][0]["input_schema"]["properties"]["value"]["enum"] == ["exact"]
    assert "untrusted" not in raw and len(data["identity"]) == 64
    fail(writer, secret)
    assert secret not in mcp_catalog.catalog_path("demo").read_text()


def test_next_registry_read_adopts_changed_file_but_resident_array_is_frozen(monkeypatch, tmp_path):
    install_settings(monkeypatch, settings())
    writer = publisher()
    writer.refresh_server("demo")
    reader = publisher()
    monkeypatch.setattr(mcp_client, "_manager", reader)
    registry = ToolRegistry(repo_dir=tmp_path, drive_root=tmp_path / "fork")
    resident = registry.schemas()
    frozen = copy.deepcopy(resident)
    async def updated(cfg, timeout):
        return listing("new")
    writer._async_list_tools = updated
    writer.refresh_server("demo")
    assert names(reader) == ["mcp_demo__ping"]
    assert registry.get_schema_by_name("mcp_demo__new") is not None
    assert names(reader) == ["mcp_demo__new"] and resident == frozen
    assert registry.get_schema_by_name("mcp_demo__ping") is None


@pytest.mark.parametrize("complete_first", [False, True])
def test_truncated_listing_cannot_replace_complete_catalog(complete_first):
    writer = publisher(items=listing("known") if complete_first else [])
    if complete_first:
        writer.refresh_server("demo")
    async def truncated(cfg, timeout):
        return listing("partial") + [{"_pagination_truncated": True}]
    writer._async_list_tools = truncated
    assert writer.refresh_server("demo")["ok"]
    envelope = json.loads(mcp_catalog.catalog_path("demo").read_text())
    assert envelope["complete"] is complete_first
    assert envelope["latest_attempt"]["partial"]
    assert names(writer) == ["mcp_demo__known" if complete_first else "mcp_demo__partial"]
    assert writer.resolve_tool_name("mcp_demo__missing").status == "catalog_unavailable"
    assert "PARTIAL" in writer.catalog_notices()[0]["detail"]


def test_empty_success_replaces_catalog_and_proves_absence():
    writer = publisher()
    writer.refresh_server("demo")
    async def empty(cfg, timeout):
        return []
    writer._async_list_tools = empty
    writer.refresh_server("demo")
    assert names(writer) == []
    status = writer.status_payload()["servers"][0]
    assert status["listed_at"] and status["complete"] and status["latest_attempt"]["ok"]
    miss = writer.resolve_tool_name("mcp_demo__ping").refusal("mcp_demo__ping")
    assert miss.code == "UNKNOWN_TOOL" and f"absent from the listing of {status['listed_at']}" in miss.text
    assert writer.catalog_notices() == [] and writer.enabled_servers_without_tools()


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("removed", [False, True])
def test_inflight_result_for_changed_or_removed_server_writes_nothing(failure, removed):
    writer = publisher()
    async def changed(cfg, timeout):
        writer.reconfigure({"MCP_ENABLED": True, "MCP_SERVERS": []} if removed else settings(url="https://new.test/mcp"))
        if failure:
            raise RuntimeError("obsolete")
        return listing("obsolete")
    writer._async_list_tools = changed
    result = writer.refresh_server("demo")
    assert not result["published"] and "stale" in result["error"]
    assert not mcp_catalog.catalog_path("demo").exists() and names(writer) == []


def test_write_failure_keeps_local_listing_but_never_claims_publication(monkeypatch):
    writer = publisher()
    writer.refresh_server("demo")
    before = mcp_catalog.catalog_path("demo").read_bytes()
    async def changed(cfg, timeout):
        return listing("new")
    writer._async_list_tools = changed
    monkeypatch.setattr(mcp_catalog, "publish", Mock(side_effect=OSError("disk full")))
    result = writer.refresh_server("demo")
    assert result["ok"] and not result["published"] and "disk full" in result["publication_error"]
    writer.reload_catalogs()
    assert names(writer) == ["mcp_demo__new"]
    assert mcp_catalog.catalog_path("demo").read_bytes() == before
    assert names(publisher()) == ["mcp_demo__ping"]
    assert "publication failed" in writer.catalog_notices()[0]["detail"]


@pytest.mark.parametrize("server_id", ["con", "nul", "aux", "com1"])
def test_windows_reserved_ids_use_safe_filenames(server_id):
    writer = publisher(settings(id=server_id))
    assert writer.refresh_server(server_id)["published"]
    assert mcp_catalog.catalog_path(server_id).name == f"server-{server_id}.json"
    assert names(publisher(settings(id=server_id))) == [f"mcp_{server_id}__ping"]


def test_stat_cache_does_not_reparse_unchanged_files(monkeypatch):
    writer = publisher()
    writer.refresh_server("demo")
    reader = publisher()
    original = json.loads
    spy = Mock(wraps=original)
    monkeypatch.setattr(mcp_catalog.json, "loads", spy)
    reader.reload_catalogs()
    reader.reload_catalogs()
    spy.assert_not_called()


def test_refresh_endpoint_publishes_test_does_not_and_status_never_prunes(monkeypatch):
    from ouroboros.gateway import mcp as api
    value = settings()
    install_settings(monkeypatch, value)
    monkeypatch.setattr(api, "load_settings", lambda: value)
    writer = publisher()
    monkeypatch.setattr(mcp_client, "_manager", writer)
    app = TestClient(Starlette(routes=api.mcp_routes()))
    assert app.post("/api/mcp/test", json={"server": value["MCP_SERVERS"][0]}).json()["ok"]
    assert not mcp_catalog.catalog_path("demo").exists()
    assert app.post("/api/mcp/refresh", json={"server_id": "demo"}).json()["published"]
    assert names(publisher()) == ["mcp_demo__ping"]
    value["MCP_SERVERS"] = []
    assert app.get("/api/mcp/status").json()["servers"] == []
    assert mcp_catalog.catalog_path("demo").exists()
    writer.become_lister()
    mcp_client.ensure_configured_from_settings()
    assert not mcp_catalog.catalog_path("demo").exists()


@pytest.mark.parametrize("is_server", [False, True])
def test_mtime_settings_event_prunes_and_relists_only_in_server(monkeypatch, is_server):
    value = settings()
    install_settings(monkeypatch, value)
    writer = publisher(value)
    writer.refresh_server("demo")
    reader = mcp_client.get_manager()
    if is_server:
        reader.become_lister()
    schedule = Mock()
    monkeypatch.setattr(reader, "refresh_all_background", schedule)
    mcp_client.ensure_configured_from_settings()
    schedule.reset_mock()
    assert names(reader)
    value["MCP_SERVERS"] = []
    config.SETTINGS_PATH.write_text(json.dumps(value))
    mcp_client.ensure_configured_from_settings()
    assert names(reader) == []
    assert mcp_catalog.catalog_path("demo").exists() is not is_server
    assert schedule.call_count == int(is_server)


def test_settings_save_env_target_uses_full_fingerprint_and_prunes(monkeypatch):
    from ouroboros.gateway.settings import _apply_settings_save_side_effects
    value = settings(transport="stdio", url="", command="server", env_from_settings={"TOKEN": "SAVED"})
    value["SAVED"] = "one"
    writer = publisher(value)
    writer.refresh_server("demo")
    monkeypatch.setattr(mcp_client, "_manager", writer)
    schedule = Mock()
    monkeypatch.setattr(writer, "refresh_all_background", schedule)
    old = copy.deepcopy(value)
    value["SAVED"] = "two"
    request = Mock()
    _apply_settings_save_side_effects(request, value, old, ["SAVED"])
    assert schedule.call_count == 1 and not mcp_catalog.catalog_path("demo").exists()
    schedule.reset_mock()
    _apply_settings_save_side_effects(request, value, value, ["UNRELATED"])
    schedule.assert_not_called()
    assert writer.refresh_server("demo")["published"]
    old = copy.deepcopy(value)
    value["MCP_SERVERS"] = []
    _apply_settings_save_side_effects(request, value, old, ["MCP_SERVERS"])
    assert schedule.call_count == 1 and not mcp_catalog.catalog_path("demo").exists()


def test_configuration_events_coalesce_one_more_pass(monkeypatch):
    writer = publisher()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    async def blocked(cfg, timeout):
        calls.append(cfg.url)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        else:
            finished.set()
        return listing("ping")
    writer._async_list_tools = blocked
    writer.refresh_all_background(reason="startup")
    try:
        assert entered.wait(5)
        writer.configuration_changed(settings(url="https://middle.test/mcp"), reason="settings")
        writer.configuration_changed(settings(url="https://latest.test/mcp"), reason="settings")
    finally:
        release.set()
    assert finished.wait(5)
    # Join the walk by taking the per-server lock after its second result.
    with writer._listing_locks["demo"]:
        assert calls == ["https://example.test/mcp", "https://latest.test/mcp"]
    assert names(publisher(settings(url="https://latest.test/mcp"))) == ["mcp_demo__ping"]


def test_same_server_refreshes_are_serial_without_blocking_manager_reads():
    writer = publisher()
    entered, release = threading.Event(), threading.Event()
    calls, results = [], []
    async def blocked(cfg, timeout):
        calls.append(cfg.id)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return listing("ping")
    writer._async_list_tools = blocked
    threads = [threading.Thread(target=lambda: results.append(writer.refresh_server("demo"))) for _ in range(2)]
    threads[0].start()
    assert entered.wait(5)
    threads[1].start()
    try:
        assert writer.status_payload()["servers"][0]["listed_at"] is None
        assert calls == ["demo"]
    finally:
        release.set()
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
    assert len(results) == 2 and all(row["published"] for row in results)


def test_forked_manager_does_not_inherit_lister_role(monkeypatch):
    value = settings()
    install_settings(monkeypatch, value)
    manager = mcp_client.get_manager()
    manager.become_lister()
    schedule = Mock()
    monkeypatch.setattr(manager, "refresh_all_background", schedule)
    mcp_client.ensure_configured_from_settings()
    assert schedule.call_count == 1
    schedule.reset_mock()
    manager._lister_pid += 1  # A different process owns the inherited role.
    value["MCP_SERVERS"] = []
    config.SETTINGS_PATH.write_text(json.dumps(value))
    mcp_client.ensure_configured_from_settings()
    schedule.assert_not_called()


def test_dispatch_adopts_newly_published_name_before_resolving(monkeypatch, tmp_path):
    from ouroboros.tools.tool_result import ToolResult
    install_settings(monkeypatch, settings())
    writer = publisher(items=[])
    writer.refresh_server("demo")
    reader = publisher()
    monkeypatch.setattr(mcp_client, "_manager", reader)
    registry = ToolRegistry(repo_dir=tmp_path, drive_root=tmp_path)
    calls = []
    async def call(cfg, name, arguments, timeout):
        calls.append(name)
        return ToolResult(status="ok", code="OK", text="called")
    reader._async_call_tool = call
    monkeypatch.setattr("ouroboros.safety.check_safety", lambda *a, **kw: (True, ""))
    assert registry.execute_result("mcp_demo__ping", {}).code == "UNKNOWN_TOOL"
    writer._async_list_tools = publisher()._async_list_tools
    writer.refresh_server("demo")
    assert registry.execute_result("mcp_demo__ping", {}).status == "ok"
    assert calls == ["ping"]
