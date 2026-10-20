import json
from types import SimpleNamespace

from ouroboros.triad_review import (
    emit_review_model_error_events,
    extract_json_array,
    parse_seat_answers,
)


def test_extract_json_array_handles_fences_and_normalizes():
    raw = "```json\n[{\"item\":\"x\",\"verdict\":\"PASS\",\"severity\":\"critical\",\"reason\":\"ok\"}]\n```"
    parsed = extract_json_array(raw, normalize=True)
    assert parsed[0]["item"] == "x"


def test_extract_json_array_tries_later_fenced_chunks_when_first_is_malformed():
    raw = (
        "```json\n"
        "[{\"item\":\"bad\",\"verdict\":\"FAIL\",}]\n"
        "```\n"
        "```json\n"
        "[{\"item\":\"good\",\"verdict\":\"PASS\",\"severity\":\"critical\",\"reason\":\"ok\"}]\n"
        "```"
    )
    parsed = extract_json_array(raw, normalize=True)
    assert parsed[0]["item"] == "good"


def test_extract_json_array_normalizes_obligation_suffix():
    raw = json.dumps([
        {
            "item": "code_quality (obligation obl-0001)",
            "verdict": "PASS",
            "severity": "critical",
            "reason": "fixed",
        }
    ])
    parsed = extract_json_array(raw, normalize=True)
    assert parsed[0]["item"] == "code_quality"
    assert parsed[0]["obligation_id"] == "obl-0001"


def test_a_single_question_seat_answers_the_findings_array_and_may_omit_items():
    """Contract A for a result or skill seat (owner 21.10, 2A): problems only; a seat that said nothing about an
    item still counts for what it said, and ``[]`` + NO_FINDINGS is a clean answer."""
    one = json.dumps([{"item": "a", "verdict": "FAIL", "severity": "critical", "reason": "bad"}])
    parsed = parse_seat_answers({"results": [
        {"model": "m1", "slot_id": "s1", "text": one},
        {"model": "m2", "slot_id": "s2", "text": "[]\nNO_FINDINGS"},
        {"model": "m3", "slot_id": "s3", "text": "I cannot review this."},
    ]}, {"s1": ("skill",), "s2": ("skill",), "s3": ("skill",)})

    assert parsed.responsive_models == ["m1 [s1]", "m2 [s2]"]
    assert [r.status for r in parsed.actor_records] == ["responded", "responded", "parse_failure"]
    assert parsed.actor_records[0].answers["skill"]["verdict"] == "FAIL"
    assert parsed.actor_records[1].answers["skill"] == {"status": "responded", "verdict": "PASS", "findings": [],
                                                       "critical": 0, "coverage": "n/a"}
    assert [f["item"] for f in parsed.findings] == ["a"]


def test_a_declared_severity_policy_decides_the_seats_verdict_before_it_is_read():
    """The skill rule (hard-critical items block whatever the seat says; advisory-only items never block;
    an item the policy does not name follows its default) is applied while parsing, so the seat verdict the
    quorum counts already carries it."""
    text = json.dumps([
        {"item": "hard", "verdict": "FAIL", "severity": "advisory", "reason": "seat said advisory"},
        {"item": "soft", "verdict": "FAIL", "severity": "critical", "reason": "seat said critical"},
        {"item": "own", "verdict": "FAIL", "severity": "warning", "reason": "seat keeps its word"},
        {"item": "invented", "verdict": "FAIL", "severity": "critical", "reason": "not a checklist item"},
    ])
    policy = {"hard": "critical", "soft": "advisory", "own": "seat", "*": "advisory"}
    parsed = parse_seat_answers({"results": [{"model": "m1", "slot_id": "s1", "text": text}]},
                                {"s1": ("skill",)}, severity_policy=policy)
    answer = parsed.actor_records[0].answers["skill"]
    assert {f["item"]: f["severity"] for f in answer["findings"]} == {
        "hard": "critical", "soft": "advisory", "own": "advisory", "invented": "advisory"}
    assert (answer["verdict"], answer["critical"]) == ("FAIL", 1)
    # Without a policy the seat's own severities stand (a change seat today).
    plain = parse_seat_answers({"results": [{"model": "m1", "slot_id": "s1", "text": text}]}, {"s1": ("skill",)})
    assert plain.actor_records[0].answers["skill"]["critical"] == 2


def test_quorum_and_degraded_reasons_follow_the_responsive_seats():
    good = json.dumps([{"item": "a", "verdict": "PASS", "severity": "critical", "reason": "ok"}])
    parsed = parse_seat_answers({"results": [
        {"model": "m1", "slot_id": "s1", "verdict": "REVIEW", "text": good},
        {"model": "m2", "slot_id": "s2", "verdict": "REVIEW", "text": good},
        {"model": "m3", "slot_id": "s3", "verdict": "ERROR", "text": "boom"},
    ]}, {})

    assert parsed.quorum_met is True
    assert parsed.degraded_reasons == ["DEGRADED: m3=error (quorum still met)"]


def test_responsive_identity_is_the_stable_slot_when_model_label_drifts():
    good = json.dumps([{"item": "a", "verdict": "PASS", "severity": "critical", "reason": "ok"}])
    parsed = parse_seat_answers({"results": [
        {"model": "model-before", "slot_id": "slot-1", "text": good},
    ]}, {"slot-1": ("change",)})

    assert parsed.responsive_models == ["model-before [slot-1]"]
    assert parsed.actor_records[0].slot_id == "slot-1"


def test_emit_review_model_error_events(tmp_path):
    good = json.dumps([{"item": "a", "verdict": "PASS", "severity": "critical", "reason": "ok"}])
    parsed = parse_seat_answers({
        "results": [
            {"model": "m1", "slot_id": "s1", "verdict": "REVIEW", "text": good},
            {"model": "m2", "slot_id": "s2", "verdict": "ERROR", "text": "boom"},
        ]
    }, {})
    logs = tmp_path / "logs"
    logs.mkdir()
    ctx = SimpleNamespace(drive_logs=lambda: logs)

    emit_review_model_error_events(ctx, parsed, source="skill_review", skill_name="demo")

    data = (logs / "events.jsonl").read_text(encoding="utf-8")
    assert '"review_model_error"' in data
    assert '"skill": "demo"' in data
