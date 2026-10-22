"""The owner editor, Main facts and failure notice read the same sourced window."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from ouroboros import capability_evidence as ce, context_fit as cf
from ouroboros.context_view_facts import window_fact, window_projection
from ouroboros.context_window import resolve_window
from ouroboros.gateway import settings as gateway
from ouroboros.loop_model_call import _remember_main_fit
from ouroboros.loop_transport import provider_terminal_fallback_text
from tests.test_context_fit_integration import _plan, _ANCHOR


@pytest.mark.parametrize("retired,metadata,typed,expected", [
    (True, 400000, 0, 400000), (True, 0, 0, None),
    (False, 400000, 0, 1000000), (False, 400000, 250000, 250000),
])
def test_settings_reads_stored_window_and_matches_main(tmp_path, monkeypatch, retired, metadata, typed, expected):
    route = dict(provider="openai-compatible", model="openai-compatible::fixture", base_url="https://fixture.invalid/v1")
    settings = dict(OUROBOROS_MODEL=route["model"], OPENAI_COMPATIBLE_BASE_URL=route["base_url"],
                    OPENAI_COMPATIBLE_API_KEY="fixture", OUROBOROS_MODEL_CONTEXT_WINDOWS={"main": typed})
    monkeypatch.setattr(gateway, "load_settings", lambda: settings)
    monkeypatch.setattr(gateway, "_owner_audit", lambda *a: None)
    monkeypatch.setattr(ce, "canonical_evidence_root", lambda: tmp_path)
    monkeypatch.setattr(ce, "_provider_metadata_window", lambda *a, **k: pytest.fail("Settings fetched metadata"))
    ack = ce.record_owner_ack(tmp_path, **route, window_tokens=1000000,
                              note="owner-confirmed via settings save" if retired else "typed")
    if metadata:
        ce._store_evidence(tmp_path, "probes", ack["route_fp"], ce.CapabilityEvidence(
            metadata, "confirmed", "provider_metadata", ack["route_fp"], ts=ce.utc_now_iso()).to_json())
    before = ce._store_path(tmp_path).read_bytes()
    app = Starlette(routes=[Route("/api/settings", gateway.api_settings_get)])
    app.state.drive_root = tmp_path
    with TestClient(app) as client:
        response = client.get("/api/settings", params={"response_limit_preview": "1", "model": route["model"]})
    assert response.status_code == 200
    preview = response.json()
    assert preview["window"]["tokens"] == expected
    evidence = ce.with_role_window(ce.probe(tmp_path, **route, allow_fetch=False), typed)
    record = resolve_window(evidence, 65536, root=tmp_path)
    assert preview["window"] == window_projection(record)
    assert preview["window_ack"] and preview["window_route"]["route_fp"] == ack["route_fp"]
    assert ("old confirmation 1,000,000" in preview["window"]["text"]) is retired
    assert ("not used" in preview["window"]["text"]) is retired
    assert bool(preview["window"]["contradiction"]) is (not retired)
    plan = replace(_plan(preferred="max"), window_record=record, window_tokens=record.total_equivalent,
                   status="confirmed" if expected else "unprobeable")
    assert window_fact(plan, 65536) == preview["window"]["text"]
    if expected is None:
        from ouroboros.llm_attempt import main_context_fit_refusal
        from ouroboros.usage_accounting import AttemptRequest
        fit = cf.measure_main_fit(plan, [{"role": "user", "content": "x" * 2_000_000}], [],
                                  profile="owner_max", rendered_mode="max", round_id="r")
        assert not fit.predicted_capacity_miss
        assert main_context_fit_refusal(AttemptRequest(model=plan.model, provider=plan.provider,
            prompt_tokens_bounded_estimate=500000, physical_context=cf._physical_context_for_fit(fit))) is None
    assert ce._store_path(tmp_path).read_bytes() == before


@pytest.mark.parametrize("kind,stated", [("bad_request", False), ("request_too_large", False),
                                       ("context_overflow", True), ("auth_error", False)])
def test_terminal_notice_carries_the_captured_window_and_honest_request_size(tmp_path, monkeypatch, kind, stated):
    monkeypatch.setattr(ce, "canonical_evidence_root", lambda: tmp_path)
    evidence = ce.CapabilityEvidence(400000, "asserted", "user_setting", "route")
    record = resolve_window(evidence, 65536, root=tmp_path)
    plan = replace(_plan(), window_record=record, window_tokens=record.total_equivalent)
    fit = cf.measure_main_fit(plan, [{"role": "user", "content": "request"}], [], anchor=_ANCHOR,
                              profile="owner_max", rendered_mode="max", round_id="r")
    usage = {"_last_llm_error_kind": kind,
             "_last_llm_provider_message": "Input length (412345 tokens) exceeds the maximum allowed length (400000 tokens)."
             if stated else "Upstream request failed"}
    _remember_main_fit(SimpleNamespace(accumulated_usage=usage), fit)
    # Later evidence must not rewrite the window this failed request assumed.
    from ouroboros.context_window import record_observation
    record_observation(tmp_path, "route", refused=200000)
    notice = provider_terminal_fallback_text(usage, is_context_overflow=kind == "context_overflow",
        is_transport_wait=False, waited_sec=0, is_deadline_exhausted=False)
    if kind == "auth_error":
        assert "assumed window" not in notice
    else:
        assert "assumed window 400,000 total: set by you" in notice
        assert "reply reserve 65,536" in notice
        assert ("provider stated" in notice) is stated
        assert ("request input estimated" in notice) is not stated
        if stated:
            assert "412,345" in notice


def test_subscription_preview_reads_only_stored_account_facts(tmp_path, monkeypatch):
    from ouroboros.llm import LLMClient
    from ouroboros.response_limits import response_limit_preview

    model = "claudexor::fixture-source=model"
    options = dict(source_id="fixture-source", credential_profile_id="account-a", account_fingerprint="fingerprint-a")
    fp = ce.route_fingerprint(provider="claudexor", model=model, options=options)
    ce._store_evidence(tmp_path, "probes", fp, ce.CapabilityEvidence(400000, "confirmed", "provider_metadata", fp,
        model=model, provider="claudexor", ts=ce.utc_now_iso(), provenance="fixture", **options).to_json())
    monkeypatch.setattr(LLMClient, "claudexor_model_catalog", lambda *a, **kw: pytest.fail("Settings fetched catalog"))
    route = dict(provider="claudexor", model=model, base_url="", use_local=False)
    before = ce._store_path(tmp_path).read_bytes()
    assert response_limit_preview(tmp_path, route, account="account-a")["window"]["tokens"] == 400000
    assert response_limit_preview(tmp_path, route, account="account-b")["window"]["tokens"] is None
    assert ce._store_path(tmp_path).read_bytes() == before
