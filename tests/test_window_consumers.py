"""All planners share declared/refused limits, with their own reserves and account scope."""
from dataclasses import replace
import json

import pytest

from ouroboros import capability_evidence as ce, context_fit as cf, reviewer_window as rw
from ouroboros.context_window import record_observation, resolve_window


@pytest.fixture
def route(tmp_path, monkeypatch):
    from ouroboros import config, server_runtime

    settings = {"OUROBOROS_MODEL": "openai-compatible::fixture", "OPENAI_COMPATIBLE_API_KEY": "account-a",
                "OPENAI_COMPATIBLE_BASE_URL": "https://fixture.invalid/v1"}
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "runtime_settings", lambda: dict(settings))
    monkeypatch.setattr(server_runtime, "apply_runtime_provider_defaults", lambda s: (s, False, []))
    monkeypatch.setattr(ce, "canonical_evidence_root", lambda: tmp_path)
    monkeypatch.setattr(cf, "_route_calibration_ratio", lambda *_a, **_kw: 1.0)
    route, _ = cf._context_route({})
    return tmp_path, settings, route


@pytest.mark.parametrize("kind", ["input", "total"])
def test_main_review_and_light_share_refusal_and_charge_their_own_reserve(route, monkeypatch, kind):
    from ouroboros import consolidator, memory_fallback
    from ouroboros.tools.review_helpers import calibrated_input_token_limit
    from tests.test_consolidator_context_fit import _LLM

    root, settings, target = route
    fp = ce.route_fingerprint(provider=target["provider"], model=target["model"], base_url=target["base_url"])
    metadata = ce.CapabilityEvidence(100_000, "confirmed", "provider_metadata", fp, ts=ce.utc_now_iso())
    ce._store_evidence(root, "probes", fp, metadata.to_json())
    record_observation(root, target["window_observation_fp"], refused=60_000, kind=kind)
    actual, evidence = cf.resolve_context_fit_route({}, allow_fetch=False)
    main = resolve_window(evidence, 65_536, root=root, observation_fp=actual["window_observation_fp"])
    assert main.usable == (34_464 if kind == "input" else 0)
    sized = rw.reviewer_context_window(target["model"], use_local=False, allow_fetch=False)
    monkeypatch.setattr(ce, "resolve_review_token_density", lambda *_a, **_kw: (1.0, "test"))
    expected = 60_000 if kind == "input" else 50_000
    assert calibrated_input_token_limit(target["model"], context_window=sized,
        output_reserve=10_000, tokenizer_margin=0) == expected
    binding = dict(model=target["model"], use_local=False, model_account_override="")
    light_limit, _measure = memory_fallback._light_fit(binding)
    assert light_limit == (60_000 if kind == "input" else 60_000 - memory_fallback.ANSWER_RESERVE_TOKENS)
    from ouroboros.response_limits import response_limit_preview
    preview = response_limit_preview(root, target, settings=settings, role="light")
    assert preview["window"]["usable"] == light_limit
    assert preview["window"]["reserve"] == memory_fallback.ANSWER_RESERVE_TOKENS
    monkeypatch.setattr(consolidator, "_light_dispatch_binding", lambda: binding)
    for fits in (True, False):
        monkeypatch.setattr(cf, "estimate_context_prompt_tokens", lambda *_a, **_kw: light_limit + (not fits))
        llm = _LLM()
        text, _usage = consolidator._call_consolidation_llm(llm, "whole input", "test")
        assert bool(text) is fits and bool(llm.calls) is fits
    settings["OPENAI_COMPATIBLE_API_KEY"] = "account-b"
    other = rw.reviewer_context_window(target["model"], use_local=False, allow_fetch=False)
    assert rw.reviewer_input_limit(other, 10_000) == 90_000
    assert memory_fallback._light_fit(binding)[0] == 100_000 - memory_fallback.ANSWER_RESERVE_TOKENS


def test_reviewer_uses_shared_role_ack_metadata_order_and_stale_is_layout_only(route, monkeypatch):
    from ouroboros import model_slots

    root, settings, target = route
    ack_route = {key: target[key] for key in ("provider", "model", "base_url")}
    ack = ce.record_owner_ack(root, **ack_route, window_tokens=1_000_000, note="owner-confirmed via settings save")
    metadata = ce.CapabilityEvidence(400_000, "confirmed", "provider_metadata", ack["route_fp"], ts=ce.utc_now_iso())
    ce._store_evidence(root, "probes", ack["route_fp"], metadata.to_json())
    def read():
        return rw.resolve_reviewer_window(target["model"], use_local=False, model_role="deep_review", allow_fetch=False)
    assert read().sizing_window() == 400_000 and read().window_record.retired_ack
    ce.record_owner_ack(root, **ack_route, window_tokens=900_000, note="typed")
    assert read().sizing_window() == 900_000 and read().window_record.contradicted_by.tokens == 400_000
    settings[model_slots.MODEL_CONTEXT_WINDOWS_KEY] = json.dumps({"deep_review": 250_000})
    monkeypatch.setattr(model_slots, "runtime_setting", lambda key, default="": settings.get(key, default))
    record_observation(root, target["window_observation_fp"], refused=300_000)
    resolved = read()
    assert resolved.sizing_window() == 250_000 and resolved.sizing_source == "user_setting"
    assert resolved.observed_at == "" and resolved.window_record.contradicted_by.tokens == 400_000
    settings.pop(model_slots.MODEL_CONTEXT_WINDOWS_KEY)
    ce.revoke_owner_ack(root, ack["route_fp"])
    ce._save(root, {"probes": {ack["route_fp"]: replace(metadata, ts="2000-01-01T00:00:00+00:00").to_json()}})
    resolved = read()
    assert resolved.stale and resolved.sizing_window() == rw.REVIEWER_FULL_WINDOW
    assert resolved.sizing_source == "layout_assumption" and resolved.window_record.usable is None
    assert not ce.is_known(resolved, require_fresh=True)
    assert rw.ReviewerWindow().sizing_window() == rw.REVIEWER_FULL_WINDOW
