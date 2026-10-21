"""Bounded review memory keeps flags without turning routine SAFE work into a hold."""
import json

from tests._safety_fixtures import supervisor as supervisor_fixture
supervisor = supervisor_fixture


def test_safe_history_compacts_but_flagged_speech_stays_mandatory(supervisor, monkeypatch):
    h = supervisor
    monkeypatch.setattr(h.module, "_SAFETY_PRIOR_BYTE_BUDGET", 1000)
    h.replies.append({"status": "DANGEROUS", "reason": "Keep this flagged reason"})
    assert not h.module.check_safety("place_reply", {"text": "flagged"}, ctx=h.ctx)[0]
    for n in range(12):
        h.replies.append({"status": "SAFE", "reason": "An ordinary checked action" * 3})
        assert h.module.check_safety("write_remote", {"step": n}, ctx=h.ctx)[0]
    prompt = h.calls[-1]["user_prompt"]
    assert "Keep this flagged reason" in prompt
    assert '"earlier_safe_verdicts_omitted":' in prompt
    history = h.module._PRIOR_VERDICTS["work"]
    assert history.omitted_safe > 0 and len(json.dumps(history).encode()) <= 1000
    count = len(h.calls)
    assert h.module.check_safety("place_reply", {"text": "flagged"}, ctx=h.ctx)[0]
    assert len(h.calls) == count  # compaction did not discard the deliberate reissue
    for n in range(10):
        h.replies.append({"status": "DANGEROUS", "reason": "Decisive flagged evidence" * 3})
        ok, message = h.module.check_safety("place_reply", {"text": f"flag-{n}"}, ctx=h.ctx)
        assert not ok
        if "TOO_LARGE" in message:
            break
    else:
        raise AssertionError("Flagged history must hold when decisive evidence does not fit")
    assert "Retry when review is available" not in message
    count = len(h.calls)
    h.replies.append({"status": "DANGEROUS", "reason": "Decisive flagged evidence" * 3})
    assert not h.module.check_safety("place_reply", {"text": f"flag-{n}"}, ctx=h.ctx)[0]
    assert len(h.calls) == count + 1  # a hold did not earn speech retry authority


def test_root_limit_evicts_retry_authority_without_holding_new_work(supervisor):
    h = supervisor
    h.ctx.task_id = "old-flag"
    h.replies.append({"status": "DANGEROUS", "reason": "Flagged"})
    assert not h.module.check_safety("place_reply", {"text": "same"}, ctx=h.ctx)[0]
    for n in range(512):
        h.ctx.task_id = f"root-{n}"
        assert h.module.check_safety("write_remote", {"step": n}, ctx=h.ctx)[0]
    assert len(h.module._PRIOR_VERDICTS) <= 512 and "old-flag" not in h.module._PRIOR_VERDICTS
    h.ctx.task_id = "root-0"
    assert h.module.check_safety("write_remote", {"step": "touch"}, ctx=h.ctx)[0]
    h.ctx.task_id = "old-flag"
    h.replies.append({"status": "DANGEROUS", "reason": "Flagged again"})
    assert not h.module.check_safety("place_reply", {"text": "same"}, ctx=h.ctx)[0]
    assert "root-0" in h.module._PRIOR_VERDICTS and "root-1" not in h.module._PRIOR_VERDICTS
    assert h.module.check_safety("place_reply", {"text": "same"}, ctx=h.ctx)[0]
