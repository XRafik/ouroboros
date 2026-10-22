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
