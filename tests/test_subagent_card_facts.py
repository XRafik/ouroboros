"""Actual metadata frames feed the card's shared Python/JS fixture."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ouroboros.subagent_messages import SUBAGENT_MESSAGE_FIELDS, subagent_message_meta
from ouroboros.subagent_runtime import cognitive_route_billing_basis

CASES = json.loads((Path(__file__).parent / "fixtures/subagent_card_facts.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_producer_metadata_carries_the_card_facts(case):
    frame = subagent_message_meta(case["task"], task_id="child", event="running")
    expected = {key: "" for key in ("subagent_task_id", "root_task_id", "parent_task_id", "delegation_role",
        "subagent_role", "write_surface", "task_group_id", "model_lane", "effective_model_lane", "model",
        "executor_route", "effort_level", "effort_requested", "effort_source")}
    expected.update(subagent_task_id="child", delegation_role="subagent", subagent_event="running", **case["facts"])
    assert frame == expected
    assert set(frame) <= set(SUBAGENT_MESSAGE_FIELDS), "speech persistence must retain the same facts"
    assert subagent_message_meta({"model": "root-model"}) == {}


@pytest.mark.parametrize("price", [None, .001])
@pytest.mark.parametrize("model,local,cost,billing", [
    ("openai/gpt-5", False, None, "unknown"),
    ("openai/gpt-5", False, .125, "measured"),
    ("future-provider/reviewer", False, 0.0, "measured"),
    ("local-model", True, None, "unknown"),
    ("claudexor::codex=gpt-5", False, None, "subscription"),
])
def test_billing_basis_ignores_price_cache_and_requires_observed_cost(monkeypatch, price, model, local, cost, billing):
    consulted = []
    def estimate(*_args, **_kwargs):
        consulted.append(True)
        return price
    monkeypatch.setattr("ouroboros.pricing.estimate_cost_optional", estimate)
    route, actual = cognitive_route_billing_basis(model, use_local=local, cost=cost)
    assert route == model + (" (local)" if local else "") and actual == billing
    ctx = SimpleNamespace(_accumulated_usage={"cost": cost, "_last_llm_call_meta": {"model": model}})
    assert cognitive_route_billing_basis(model, use_local=local, ctx=ctx) == (route, billing)
    assert not consulted, "a billing fact cannot depend on the cache or pricing service"
