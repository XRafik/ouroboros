"""Planning evidence is exact-route, and I/T/O/R are independent facts."""
from dataclasses import replace

import pytest

from ouroboros import capability_evidence as ce
from ouroboros.context_window import WindowLimit, WindowRecord, record_observation, resolve_window


@pytest.mark.parametrize("input_limit,total,expected", [(200_000, None, 200_000),
    (None, 200_000, 134_464), (150_000, 200_000, 134_464), (100_000, 200_000, 100_000)])
def test_reserve_is_charged_once_only_to_a_total(input_limit, total, expected):
    record = WindowRecord("r", WindowLimit(input_limit, "input", "metadata") if input_limit else None,
                          WindowLimit(total, "total", "metadata") if total else None, reserve=65_536)
    assert record.usable == expected
    assert record.total_equivalent - record.reserve == expected
    assert WindowRecord("unknown", reserve=65_536).usable is None


def test_refusal_expires_or_is_superseded_only_by_a_later_larger_acceptance(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(ce, "utc_now_iso", lambda: now.isoformat())
    evidence = ce.CapabilityEvidence(872_000, "confirmed", "metadata", "r")
    record_observation(tmp_path, "r", accepted=921_227, reserve=65_536, transmitted=65_536)
    accepted = resolve_window(evidence, 65_536, root=tmp_path)
    assert accepted.total.tokens == 921_227 and accepted.usable == 855_691
    assert accepted.source.startswith("accepted")
    record_observation(tmp_path, "r", refused=200_000)
    assert resolve_window(evidence, 65_536, root=tmp_path).total.tokens == 200_000
    record_observation(tmp_path, "r", accepted=199_999)
    assert resolve_window(evidence, 65_536, root=tmp_path).source.startswith("refusal")
    record_observation(tmp_path, "r", accepted=210_000)
    assert resolve_window(evidence, 65_536, root=tmp_path).total.tokens == 921_227
    record_observation(tmp_path, "r", refused=200_000)
    monkeypatch.setattr(ce, "utc_now", lambda: now + timedelta(seconds=ce._CONFIRMED_TTL_SEC + 1))
    assert resolve_window(evidence, 65_536, root=tmp_path).total.tokens == 921_227
    assert resolve_window(replace(evidence, route_fp="other"), 65_536, root=tmp_path).total.tokens == 872_000
    assert resolve_window(evidence, 65_536, root=tmp_path, bound=False).total.tokens == 872_000


def test_numberless_refusal_adds_no_ceiling(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ouroboros.context_window import record_refusal

    monkeypatch.setattr(ce, "canonical_evidence_root", lambda: tmp_path)
    plan = SimpleNamespace(route_fp="r", window_witness_bound=True)
    evidence = ce.CapabilityEvidence(0, "unprobeable", "none", "r")
    record_refusal({"_last_llm_provider_message": "context length exceeded"}, plan)
    assert resolve_window(evidence, 65_536, root=tmp_path).usable is None
    record_refusal({"_last_llm_provider_message": "prompt is too long: 210000 tokens > 200000 maximum"}, plan)
    assert resolve_window(evidence, 65_536, root=tmp_path).usable == 200_000
