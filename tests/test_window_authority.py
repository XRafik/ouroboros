"""Window declarations, observations and their consumer-facing provenance."""
from types import SimpleNamespace

import pytest

from ouroboros import capability_evidence as ce, context_budget as cb
from ouroboros.context_window import record_refusal, resolve_window
from ouroboros.loop_llm_call import classify_llm_exception


SCHEDULER = ("Input length (412345 tokens) exceeds the maximum allowed length (400000 tokens). "
             "Use a shorter input or enable --allow-auto-truncate.")


@pytest.mark.parametrize("text,counts", [
    (SCHEDULER, (412345, 0, 0)),
    ("The input (412345 tokens) is longer than the model's context length (400000 tokens).", (412345, 0, 0)),
    ("Requested token count exceeds the model's maximum context length of 400000 tokens. "
     "You requested a total of 458000 tokens: 392464 tokens from the input messages and "
     "65536 tokens for the completion.", (392464, 65536, 458000)),
])
def test_sglang_size_refusals_keep_reply_room(tmp_path, monkeypatch, text, counts):
    monkeypatch.setattr(ce, "canonical_evidence_root", lambda: tmp_path)
    error = RuntimeError(text)
    error.status_code = 400
    error.body = {"error": {"code": 400, "message": text}}
    assert classify_llm_exception(error).kind == "context_overflow"
    assert cb.context_overflow_message(text)
    assert ce._parse_ctx_limit_number(text) == 400000
    assert ce._parse_ctx_requested(text) == counts
    record_refusal({"_last_llm_provider_message": text}, SimpleNamespace(route_fp="route"))
    record = resolve_window(ce.CapabilityEvidence(0, "unprobeable", "none", "route"), 65536, root=tmp_path)
    assert record.total.tokens == 400000 and record.input is None
    assert record.usable == 334464


@pytest.mark.parametrize("text", [
    "maximum allowed length (64 characters)", "maximum length is 128",
    "Request header field exceeds the maximum allowed length (8192)", "Upstream request failed",
])
def test_unrelated_length_errors_create_no_window(tmp_path, monkeypatch, text):
    monkeypatch.setattr(ce, "canonical_evidence_root", lambda: tmp_path)
    error = RuntimeError(text)
    error.status_code = 400
    assert classify_llm_exception(error).kind == "bad_request"
    assert not cb.context_overflow_message(text)
    assert ce._parse_ctx_limit_number(text) == 0
    record_refusal({"_last_llm_provider_message": text}, SimpleNamespace(route_fp="route"))
    assert resolve_window(ce.CapabilityEvidence(0, "unprobeable", "none", "route"), 65536, root=tmp_path).usable is None


@pytest.mark.parametrize("code,kind", [
    ("invalid_api_key", "auth_error"), ("insufficient_quota", "quota_exhausted"),
    ("rate_limit_exceeded", "provider_transient"), (400, "context_overflow"),
])
def test_typed_errors_keep_precedence(code, kind):
    error = RuntimeError(SCHEDULER)
    error.status_code = 400
    error.body = {"error": {"code": code, "message": SCHEDULER}}
    assert classify_llm_exception(error).kind == kind


@pytest.mark.parametrize("prefix", ["max_tokens: ", "request body too large: ", ""])
def test_output_and_body_errors_keep_precedence(prefix):
    error = RuntimeError(prefix + SCHEDULER)
    error.status_code = 400
    assert classify_llm_exception(error).kind == ("request_too_large" if prefix else "context_overflow")


@pytest.mark.parametrize("note,window,retired", [
    ("owner-confirmed via settings save", 1000000, True),
    ("owner-confirmed via context-mode toggle", 1000000, True),
    ("owner-confirmed via settings save", 400000, False),
    ("owner-confirmed via context-mode toggle", 400000, False),
    ("typed by owner", 1000000, False),
    ("owner-confirmed via settings save ", 1000000, False),
])
def test_only_forced_dialog_acks_retire_without_a_read_rewrite(tmp_path, monkeypatch, note, window, retired):
    from ouroboros.response_limits import record_response_ack

    route = dict(provider="openai-compatible", model="openai-compatible::fixture", base_url="https://fixture.invalid/v1")
    ack = ce.record_owner_ack(tmp_path, **route, window_tokens=window, note=note)
    record_response_ack(tmp_path, **route, max_output_tokens=4096)
    before = ce._store_path(tmp_path).read_bytes()
    evidence = ce.probe(tmp_path, **route, allow_fetch=False)
    assert evidence.window_tokens == (0 if retired else window)
    assert bool(evidence.retired_ack) is retired
    assert evidence.response_limit["max_output_tokens"] == 4096
    assert ce.list_owner_acks(tmp_path)[0]["retired"] is retired
    assert ce._store_path(tmp_path).read_bytes() == before
    assert ce._load(tmp_path)["owner_acks"][ack["route_fp"]] == ack


@pytest.mark.parametrize("mismatch", [False, True])
def test_clear_window_ack_is_exact_route_and_audited(tmp_path, monkeypatch, mismatch):
    import asyncio
    import json
    from ouroboros.gateway import settings as gateway
    from ouroboros.response_limits import record_response_ack, resolve_response_limit

    route = dict(provider="openai-compatible", model="openai-compatible::fixture", base_url="https://fixture.invalid/v1")
    ack = ce.record_owner_ack(tmp_path, **route, window_tokens=1000000)
    other = ce.record_owner_ack(tmp_path, **{**route, "model": "other"}, window_tokens=400000)
    record_response_ack(tmp_path, **route, max_output_tokens=4096)
    audit = []
    monkeypatch.setattr(gateway, "_owner_audit", lambda *args: audit.append(args[1:]))

    async def body():
        return {**route, "window_tokens": 0, "route_fp": "wrong" if mismatch else ack["route_fp"]}

    request = SimpleNamespace(json=body, app=SimpleNamespace(state=SimpleNamespace(drive_root=tmp_path)))
    response = asyncio.run(gateway.api_acknowledge_capability(request))
    assert response.status_code == (400 if mismatch else 200)
    rows = ce._load(tmp_path)["owner_acks"]
    assert (ack["route_fp"] in rows) is mismatch
    assert other["route_fp"] in rows
    assert resolve_response_limit(tmp_path, **route).max_output_tokens == 4096
    assert bool(audit) is not mismatch
    if not mismatch:
        assert json.loads(response.body)["ack"]["removed"]
        assert audit[0][0] == "capability_ack" and audit[0][1]["window_tokens"] == 0
