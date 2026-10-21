"""Hermetic Supervisor harness: real check path, fake physical model and place seams."""
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def supervisor(monkeypatch, tmp_path):
    from ouroboros import safety
    from ouroboros import tool_effects, place_guard

    values = {"OUROBOROS_MODEL_SAFETY": "", "OUROBOROS_SUBAGENTS": ""}
    modes = {"owner": "full", "consciousness": "full"}
    calls, events, replies = [], [], []
    ctx = SimpleNamespace(task_id="work", task_metadata={"work_kind": "owner"}, drive_root=tmp_path,
                          task_contract={"unbounded": "MUST NOT BE INCLUDED"})
    safety._PRIOR_VERDICTS.clear()
    monkeypatch.setattr(safety, "_SAFETY_STORM_UNTIL", 0)
    monkeypatch.setattr(safety, "runtime_setting", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(safety, "get_safety_mode", lambda kind="owner": modes[kind])
    monkeypatch.setattr(safety, "get_runtime_mode", lambda: "advanced")
    monkeypatch.setattr(safety, "get_safety_model", lambda: values.get("OUROBOROS_MODEL_SAFETY") or "test/checker")
    monkeypatch.setattr(safety, "_resolve_safety_routing", lambda: (False, False, None))
    monkeypatch.setattr(safety, "_emit_durable_safety_event", lambda ctx, event: events.append(event))
    monkeypatch.setattr(safety, "_emit_safety_mode_skip", lambda *a: events.append({"type": "skip"}))
    monkeypatch.setattr(place_guard, "call_place_facts", lambda *a, **kw: {})
    monkeypatch.setattr(tool_effects, "effect_of", lambda name, **kw: tool_effects.BUILTIN)
    def call(**kwargs):
        calls.append(kwargs)
        reply = replies.pop(0) if replies else {"status": "SAFE", "reason": "fine"}
        if isinstance(reply, Exception):
            raise reply
        return {"content": reply if isinstance(reply, str) else json.dumps(reply)}, {}
    monkeypatch.setattr(safety, "_safety_model_call", call)
    yield SimpleNamespace(module=safety, ctx=ctx, calls=calls, events=events, replies=replies, values=values, modes=modes)
    safety._PRIOR_VERDICTS.clear()
