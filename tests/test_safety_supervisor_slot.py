"""Resolved Supervisor authority through generic writers, browser and owner doors."""
import json
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from tests.test_safety_second_check import catalog
from ouroboros.gateway.owner_settings import _owner_write_settings


@pytest.fixture
def settings_root(tmp_path, monkeypatch):
    from ouroboros import config
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "get_runtime_mode", lambda: "advanced")
    for key in config.SETTINGS_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    path.write_text(json.dumps({"OUROBOROS_MODEL": "main", "OUROBOROS_MODEL_LIGHT": "light",
                               "OUROBOROS_SAFETY_MODE": "full", "OUROBOROS_CONSCIOUSNESS_SAFETY_MODE": "full"}))
    return config, path


def test_slot_inherits_light_then_main_and_local(monkeypatch):
    from ouroboros.model_slots import get_safety_model
    monkeypatch.delenv("OUROBOROS_MODEL_SAFETY", raising=False)
    monkeypatch.setenv("OUROBOROS_MODEL_LIGHT", "light")
    monkeypatch.setenv("OUROBOROS_MODEL", "main")
    monkeypatch.setenv("USE_LOCAL_LIGHT", "true")
    assert get_safety_model() == "light (local)"
    monkeypatch.setenv("OUROBOROS_MODEL_SAFETY", "chosen")
    assert get_safety_model() == "chosen"
    monkeypatch.setenv("OUROBOROS_MODEL_SAFETY", "")
    monkeypatch.setenv("OUROBOROS_MODEL_LIGHT", "")
    monkeypatch.setenv("USE_LOCAL_MAIN", "false")
    assert get_safety_model() == "main"
    monkeypatch.setenv("USE_LOCAL_MAIN", "true")
    assert get_safety_model() == "main (local)"


@pytest.mark.parametrize("change", [
    {"OUROBOROS_MODEL_LIGHT": "other"}, {"OUROBOROS_MODEL_SAFETY": "explicit"},
    {"OUROBOROS_SAFETY_MODE": "light"}, {"OUROBOROS_CONSCIOUSNESS_SAFETY_MODE": "off"},
    {"OUROBOROS_SAFETY_OWNER_RULES": "anything goes"}, {"OUROBOROS_SUBAGENTS": catalog()},
    {"OUROBOROS_MODEL_ACCOUNTS": {"safety": "different"}},
])
def test_generic_ratchet_refuses_both_direct_and_browser_change(settings_root, change, monkeypatch):
    config, path = settings_root
    before = path.read_bytes()
    with pytest.raises(PermissionError):
        config.save_settings({**config.load_settings(), **change})
    assert path.read_bytes() == before
    from ouroboros.browser_policy import _is_owner_settings_self_elevation_post
    request = SimpleNamespace(url="http://localhost/api/settings", method="POST", post_data=json.dumps(change))
    assert _is_owner_settings_self_elevation_post(request)
    request.post_data = json.dumps({"OUROBOROS_MODEL_HEAVY": "unrelated"})
    assert not _is_owner_settings_self_elevation_post(request)
    # The owner writer can make the same decision.
    _owner_write_settings({**config.load_settings(), **change}, allow_safety_lowering=True,
                         authored_keys=tuple(change))
    assert path.read_bytes() != before


def test_only_resolved_route_is_guarded(settings_root):
    config, path = settings_root
    config.save_settings({**config.load_settings(), "OUROBOROS_MODEL": "new-main"})
    assert json.loads(path.read_text())["OUROBOROS_MODEL"] == "new-main"
    with pytest.raises(PermissionError):
        config.save_settings({**config.load_settings(), "OUROBOROS_MODEL_LIGHT": ""})
    _owner_write_settings({**config.load_settings(), "OUROBOROS_MODEL_SAFETY": "fixed"}, allow_safety_lowering=True,
                         authored_keys=("OUROBOROS_MODEL_SAFETY",))
    config.save_settings({**config.load_settings(), "OUROBOROS_MODEL_LIGHT": "different-light"})
    assert json.loads(path.read_text())["OUROBOROS_MODEL_LIGHT"] == "different-light"


def test_provider_defaults_cannot_replace_an_unauthored_checker(settings_root):
    config, path = settings_root
    path.write_text(json.dumps({"OUROBOROS_CONSCIOUSNESS_SAFETY_MODE": "full"}))
    before = path.read_bytes()
    with pytest.raises(PermissionError):
        config.save_settings({"ANTHROPIC_API_KEY": "fixture-key"})
    assert path.read_bytes() == before
    from ouroboros.browser_policy import _is_owner_settings_self_elevation_post
    request = SimpleNamespace(url="http://localhost/api/settings", method="POST", post_data='{"ANTHROPIC_API_KEY":"fixture-key"}')
    assert _is_owner_settings_self_elevation_post(request)
    _owner_write_settings({"OUROBOROS_MODEL_SAFETY": "fixed/checker"},
                         allow_safety_lowering=True, authored_keys=("OUROBOROS_MODEL_SAFETY",))
    assert not _is_owner_settings_self_elevation_post(request)
    config.save_settings({**config.load_settings(), "ANTHROPIC_API_KEY": "fixture-key"})
    assert json.loads(path.read_text())["ANTHROPIC_API_KEY"] == "fixture-key"


def test_owner_endpoints_keep_mode_response_shape_and_audit(settings_root):
    config, path = settings_root
    from ouroboros.gateway import safety_settings as endpoints
    app = Starlette(routes=[
        Route("/api/owner/safety-mode", endpoints.api_owner_safety_mode, methods=["POST"]),
        Route("/api/owner/safety-rules", endpoints.api_owner_safety_rules, methods=["POST"]),
        Route("/api/owner/safety-model", endpoints.api_owner_safety_model, methods=["POST"]),
    ])
    app.state.drive_root = path.parent
    app.state.repo_dir = path.parent
    with TestClient(app) as client:
        response = client.post("/api/owner/safety-mode", json={"kind": "consciousness", "mode": "light"})
        assert response.status_code == 200 and response.json() == {"ok": True, "safety_mode": "light"}
        assert json.loads(path.read_text())["OUROBOROS_SAFETY_MODE"] == "full"
        assert client.post("/api/owner/safety-mode", json={"kind": "forged", "mode": "off"}).status_code == 400
        response = client.post("/api/owner/safety-rules", json={"rules": "May send replies in my team."})
        assert response.status_code == 200
        response = client.post("/api/owner/safety-model", json={"settings": {"OUROBOROS_MODEL_SAFETY": "chosen"}})
        assert response.status_code == 200
        assert json.loads(path.read_text())["OUROBOROS_MODEL_SAFETY"] == "chosen"
    audit = (path.parent / "logs" / "events.jsonl").read_text()
    assert "safety_mode" in audit and "safety_rules" in audit and "safety_model" in audit


def test_generic_cyber_change_is_permitted_and_audited(settings_root, monkeypatch):
    config, path = settings_root
    from ouroboros.gateway import settings
    monkeypatch.setattr(config, "get_runtime_mode", lambda: "cyber_pro")
    monkeypatch.setattr(settings, "_apply_settings_save_side_effects", lambda *a, **kw: None)
    monkeypatch.setattr(settings, "_start_supervisor_if_needed_for_request", lambda *a, **kw: False)
    app = Starlette(routes=[Route("/api/settings", settings.api_settings_post, methods=["POST"])])
    app.state.drive_root = path.parent
    app.state.repo_dir = path.parent
    with TestClient(app) as client:
        response = client.post("/api/settings", json={"OUROBOROS_MODEL_SAFETY": "changed"})
        assert response.status_code == 200, response.text
    assert json.loads(path.read_text())["OUROBOROS_MODEL_SAFETY"] == "changed"
    events = [json.loads(line) for line in (path.parent / "logs" / "events.jsonl").read_text().splitlines()]
    event = next(row for row in events if row.get("action") == "safety_settings")
    assert event["changed_settings"] == ["OUROBOROS_MODEL_SAFETY"]


def test_generic_http_save_cannot_replace_inherited_checker(settings_root, monkeypatch):
    config, path = settings_root
    from ouroboros.gateway import settings
    monkeypatch.setattr(settings, "_apply_settings_save_side_effects", lambda *a, **kw: None)
    monkeypatch.setattr(settings, "_start_supervisor_if_needed_for_request", lambda *a, **kw: False)
    app = Starlette(routes=[Route("/api/settings", settings.api_settings_post, methods=["POST"])])
    app.state.drive_root = path.parent
    app.state.repo_dir = path.parent
    with TestClient(app) as client:
        before = path.read_bytes()
        denied = client.post("/api/settings", json={"OUROBOROS_MODEL_LIGHT": "other"})
        assert denied.status_code == 400 and denied.json()["saved"] is False
        assert path.read_bytes() == before
        allowed = client.post("/api/settings", json={"OUROBOROS_MODEL_HEAVY": "unrelated"})
        assert allowed.status_code == 200
        assert json.loads(path.read_text())["OUROBOROS_MODEL_HEAVY"] == "unrelated"
