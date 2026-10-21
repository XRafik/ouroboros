"""Mind-selected memory forms share the authored boundary and preserve concurrent arrivals."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from ouroboros import memory_view as mv, memory_floor as floor
from ouroboros.context_fit import ContextCore, ContextFitPlan, ContextFitProjection, _system_blocks, _governance_blocks
from ouroboros.tools.compact_context import record_context_view, _compact_context
from ouroboros.loop_round_limits import _run_round_compaction
from tests._memory_view_synthetic import snapshot, room, spoken, pages
from tests.test_context_view_tool import _context


def plan():
    words = [spoken(0, "human", 4000), spoken(1, "ouroboros", 4000), spoken(2, "human", 4000)]
    words[2]["immune"] = True
    snap = snapshot(room_facts=room(lane1=words), story=pages(2, 8000))
    core = ContextCore("Core", "BIBLE", "", "", "Identity", "Facts", '"Assignment"', False,
                       memory_view_json=mv.snapshot_json(snap))
    facts = floor.view_facts(snap, mv.FULL_VIEW, window_tokens=200000, mode="max", allowances={})
    content = _system_blocks(core, _governance_blocks(None, core, mode="max"), mv.render_story(snap), mv.render_room(snap))
    projection = ContextFitProjection("max", json.dumps(content), 10000, 10000, 1.0, memory_facts=facts)
    return ContextFitPlan("capture", "max", "max", "test", "test", "route", "confirmed", False, 200000,
                          65536, '"Assignment"', projection, replace(projection, mode="low"), core=core), snap


def test_addresses_refuse_core_and_governing_words_and_keep_prior_choices():
    p, snap = plan()
    first = floor.select_view(p, "max", ["F5:page-000"])
    second = floor.select_view(first, "max", ["F5:page-001"])
    assert "Page 0." in p.projection("max").system_content_json
    assert "Page 0." not in second.projection("max").system_content_json
    assert dict(floor.kept_level(snap, second.projection("max").memory_facts).addressed)["F5"] == ("page-000", "page-001")
    for address in ("core:BIBLE", "F7:" + snap.room["lane1"][-1]["address"]):
        with pytest.raises(ValueError, match="protected"):
            floor.select_view(p, "max", [address])
    assert p.core.memory_view_json == second.core.memory_view_json


@pytest.mark.parametrize("accept", [True, False])
def test_boundary_measures_before_publish_and_keeps_arrivals(tmp_path, monkeypatch, accept):
    p, snap = plan()
    ctx = SimpleNamespace(context_fit_plan=p, active_context_mode="max")
    messages, schemas = p.messages_for("max"), []
    record_context_view(ctx, messages, schemas)
    seen = json.loads(_compact_context(ctx, inspect=True))
    assert any(row.get("view_address") == "F5:page-000" for row in seen["units"])
    assert "re-read" in seen["memory_re_read_price"] or "re-reading" in seen["memory_re_read_price"]
    assert "protected" in _compact_context(ctx, view_address=["core:BIBLE"])
    assert "requested" in _compact_context(ctx, expected_view_revision=seen["view_revision"], view_address=["F5:page-000"])
    tail = [{"role": "user", "content": "A new exact owner instruction"},
            {"role": "assistant", "tool_calls": [{"id": "late", "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "late", "content": "Newly chosen exact evidence"}]
    messages += tail
    result = _run_round_compaction(messages, _context(tmp_path, ctx, schemas, monkeypatch,
        lambda m, t: {"accepted": accept, "input_tokens": floor.view_tokens(json.dumps(m))}))
    assert all(row in result for row in tail)
    assert ctx._context_view_receipt["status"] == ("applied" if accept else "fit_rejected")
    if accept:
        assert "Page 0." not in json.dumps(result[0]) and "Page 1." in json.dumps(result[0])
        assert ctx._context_view_receipt["fit_after"]["input_tokens"] > 0
        assert ctx._context_view_receipt["memory_view"]["re_read_input_tokens_estimate"] > 0
    else:
        assert result == messages and ctx.context_fit_plan is p
