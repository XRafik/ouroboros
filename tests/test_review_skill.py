"""``skill_review`` → ``review_change(subject="skill")``: one review machinery for a skill payload (owner 21.10, 1A).

Every seat of a skill wave answers the one skill question in the findings-only form over the payload frozen at
its loader hash; the wave is review_change's own (panel by strictness, custody, the paid stamp, $0 reuse, the
ledger record ``surface="skill"``), and ``state/skills/<name>/review.json`` is the run gate's projection of that
record. The seats are fake and offline (the golden physical seam); no model is ever called.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ouroboros.review_substrate as substrate
from ouroboros import review_ledger
from ouroboros.skill_loader import load_review_state
from ouroboros.tools.registry import ToolContext
from tests import _contributor_packet_shared as shared
from tests.review_pool_rosters import set_review_pool
from tests.test_skill_exec import _build_skill

CLEAN = "[]\nNO_FINDINGS"
HARD = json.dumps([{"item": "no_repo_mutation", "verdict": "FAIL", "severity": "advisory",
                    "reason": "scripts/hello.py commits to ~/Ouroboros/repo"}])
SOFT = json.dumps([{"item": "error_handling", "verdict": "FAIL", "severity": "critical",
                    "reason": "the script swallows every exception"}])
UNKNOWN = json.dumps([{"item": "invented_item", "verdict": "FAIL", "severity": "critical", "reason": "not a checklist item"}])


def _seam(sends, answers):
    def answer(request, slot, actor, *, retry_state, pending_invocation_checkpoint):
        actor.raw_text = answers.get(slot.slot_id, CLEAN)
        return actor

    return shared.golden_physical_seam(sends, answer=answer)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """A reviewable script skill in the drive's external bucket, the golden pool and an offline seam."""
    monkeypatch.setenv("OUROBOROS_USER_FILES_ROOT", str(tmp_path))
    monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "advisory")
    monkeypatch.setenv("OUROBOROS_SKILLS_REPO_PATH", "")
    monkeypatch.delenv("OUROBOROS_REVIEW_MAX_CYCLES", raising=False)
    set_review_pool(monkeypatch, shared.golden_pool())
    system = Path(shared.init_installed_body(tmp_path / "ouroboros")["repo"])
    drive = tmp_path / "ouroboros" / "data"
    for sub in ("logs", "locks", "state"):
        (drive / sub).mkdir(parents=True)
    skill_dir = _build_skill(drive / "skills" / "external", "weather")
    ctx = ToolContext(repo_dir=system, system_repo_dir=system, drive_root=drive, task_id="task-skill")
    sends, answers = [], {}
    monkeypatch.setattr(substrate.ReviewCoordinator, "_run_slot", _seam(sends, answers))
    return SimpleNamespace(ctx=ctx, drive=drive, skill_dir=skill_dir, sends=sends, answers=answers, system=system,
                           monkeypatch=monkeypatch)


def _review(harness, **kwargs):
    from ouroboros.skill_review import review_skill

    return review_skill(harness.ctx, "weather", **kwargs)


def _state(harness):
    return load_review_state(harness.drive, "weather", skill_type="script", skill_dir=harness.skill_dir)


def test_advisory_one_reviewer_with_a_reason_reviews_the_skill_and_the_same_bytes_reuse_the_record(harness):
    first = _review(harness, reviewers=["t1"], reason="small payload")
    assert (first.status, first.paid, first.reused, first.pending) == ("clean", True, False, False), first.error
    assert [send["slot_id"] for send in harness.sends] == ["t1"] and first.panel["assigned"] == ["t1"]
    record = review_ledger.load_record(harness.drive, first.record_id)
    assert record["surface"] == "skill" and record["subject"]["kind"] == "skill"
    assert record["subject"]["skill"] == "weather" and record["subject"]["content_hash"] == first.content_hash
    assert set(record["subject"]["files"]) == {"SKILL.md", "scripts/hello.py"}
    assert record["brief"]["parts"] == ["skill"] and record["brief"]["checklist"]["severity_policy"]["no_repo_mutation"] == "critical"
    assert record["brief"]["skill"]["name"] == "weather" and record["verdict"]["per_question"] == {"skill": "PASS"}
    state = _state(harness)
    assert (state.status, state.record_id, state.content_hash) == ("clean", first.record_id, first.content_hash)
    assert state.gate_for(first.content_hash, enforcement="advisory")["executable_review"] is True
    assert state.seats and state.seats[0]["seat_id"] == "t1" and state.governance["packet"]["owed_chars"] > 0

    again = _review(harness, reviewers=["t1"], reason="small payload")
    assert again.reused is True and again.record_id == first.record_id and len(harness.sends) == 1


def test_blocking_widens_to_every_ticked_reviewer_and_the_checklist_rule_decides_what_blocks(harness):
    """Blocking seats every ticked reviewer whatever the author named; a hard trust-boundary item blocks even
    when the seat called it advisory (the severity policy is applied before the verdict is read)."""
    harness.monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "blocking")
    harness.answers["t2"] = HARD
    outcome = _review(harness, reviewers=["t1"], reason="small payload")
    assert outcome.status == "blockers" and sorted(send["slot_id"] for send in harness.sends) == ["s1", "t1", "t2"]
    assert outcome.panel["assigned"] == ["t1", "t2", "s1"] and outcome.panel.get("widened_from") == ["t1"]
    [finding] = [f for f in outcome.findings if not f.get("additional")]
    assert (finding["item"], finding["severity"], finding["seat_id"], finding["part"]) == ("no_repo_mutation", "critical", "t2", "skill")
    record = review_ledger.load_record(harness.drive, outcome.record_id)
    assert record["verdict"]["aggregate"] == "FAIL" and record["verdict"]["per_row"]["t2"] == "FAIL"
    state = _state(harness)
    assert state.status == "blockers" and state.gate_for(outcome.content_hash, enforcement="blocking")["executable_review"] is False


@pytest.mark.parametrize("answer, item", [(SOFT, "error_handling"), (UNKNOWN, "invented_item")])
def test_an_advisory_item_and_an_unknown_item_warn_and_never_block(harness, answer, item):
    """Parity with today's aggregation (owner addendum 21.10 ~01:50): a FAIL on one of the four advisory items or
    on a name outside the checklist is a warning, whatever severity the seat wrote."""
    harness.answers["t1"] = answer
    outcome = _review(harness, reviewers=["t1"], reason="small payload")
    assert outcome.status == "warnings", outcome.error
    [finding] = [f for f in outcome.findings if not f.get("additional")]
    assert (finding["item"], finding["severity"]) == (item, "advisory")
    record = review_ledger.load_record(harness.drive, outcome.record_id)
    assert record["verdict"]["aggregate"] == "PASS" and record["verdict"]["advisory_findings"]
    assert _state(harness).gate_for(outcome.content_hash, enforcement="advisory")["executable_review"] is True


def test_an_unreadable_findings_array_is_no_answer_and_a_readable_entry_beside_junk_still_counts(harness):
    """A seat whose array carries no readable entry (no ``item``, no PASS/FAIL ``verdict``) has not answered:
    the one Advisory reviewer's wave stays pending and non-executable, never clean (grok 1 / astra 4); a
    seat with one readable FAIL beside junk counts for what it said."""
    harness.answers["t1"] = json.dumps([{"item": "host_token_handling", "severity": "critical", "reason": "prints the token"}])
    outcome = _review(harness, reviewers=["t1"], reason="small payload")
    assert (outcome.status, outcome.pending, outcome.paid) == ("pending", False, True), outcome.error
    assert "QUORUM_FAILED" in outcome.error or "quorum" in outcome.error.lower(), outcome.error
    record = review_ledger.load_record(harness.drive, outcome.record_id)
    assert record["verdict"]["aggregate"] == "QUORUM_FAILED" and record["rows"][0]["answers"]["skill"]["status"] == "unanswered"
    assert "none of the 1 entries has an item and a PASS/FAIL verdict" in record["rows"][0]["answers"]["skill"]["error"]
    assert _state(harness).gate_for(outcome.content_hash, enforcement="advisory")["executable_review"] is False

    (harness.skill_dir / "SKILL.md").write_text("# weather\n\nRevised.\n", encoding="utf-8")
    harness.answers["t1"] = json.dumps([{"unexpected": "not a finding"},
                                        {"item": "no_repo_mutation", "verdict": "FAIL", "severity": "advisory", "reason": "commits"}])
    outcome = _review(harness, reviewers=["t1"], reason="small payload")
    assert outcome.status == "blockers" and len(harness.sends) == 2, outcome.error
    [finding] = [f for f in outcome.findings if not f.get("additional")]
    assert (finding["item"], finding["severity"]) == ("no_repo_mutation", "critical")


# --- the brief: change-focused re-review (3A), the packet's size, the governance owed -------------------------


def _capturing_seam(sends, answers, briefs):
    """The golden seam plus what each seat was GIVEN: the packet prompt or the retrieving seat's task."""
    def answer(request, slot, actor, *, retry_state, pending_invocation_checkpoint):
        task = (request.slot_session_tasks or {}).get(slot.slot_id) or request.session_task or ""

        def text(content):  # a message's content: a string, or the provider's list of text/cache blocks
            if isinstance(content, list):
                return "\n".join(str(block.get("text") or "") for block in content if isinstance(block, dict))
            return str(content or "")

        briefs[slot.slot_id] = task or "\n".join(text(m.get("content")) for m in (request.messages or []))
        actor.raw_text = answers.get(slot.slot_id, CLEAN)
        return actor

    return shared.golden_physical_seam(sends, answer=answer)


@pytest.fixture
def briefing(harness):
    briefs: dict = {}
    harness.monkeypatch.setattr(substrate.ReviewCoordinator, "_run_slot", _capturing_seam(harness.sends, harness.answers, briefs))
    harness.briefs = briefs
    return harness


def test_a_re_review_after_an_edit_is_change_focused_in_every_mode_and_judges_the_whole_skill(briefing):
    """3A: the brief says what changed since the last verdict — added, modified and removed files with a unified
    diff from the retained earlier copy — in Advisory and in Blocking alike; the verdict is on the whole skill."""
    h = briefing
    (h.skill_dir / "docs.txt").write_text("first notes\n", encoding="utf-8")
    first = _review(h, reviewers=["t1"], reason="small payload")
    assert first.status == "clean", first.error
    (h.skill_dir / "scripts" / "hello.py").write_text("print('hello from skill, revised')\n", encoding="utf-8")
    (h.skill_dir / "scripts" / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
    (h.skill_dir / "docs.txt").unlink()
    h.briefs.clear()
    h.monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "blocking")
    second = _review(h, reviewers=["t1"], reason="small payload")
    assert second.status == "clean" and second.record_id != first.record_id and second.content_hash != first.content_hash
    for seat in ("t1", "t2", "s1"):
        brief = h.briefs[seat]
        assert f"## Changed since the previous review {first.content_hash[:12]} (clean)" in brief, seat
        assert "- added: scripts/util.py" in brief and "- modified: scripts/hello.py" in brief and "- removed: docs.txt" in brief
        assert "### diff scripts/hello.py" in brief and "+print('hello from skill, revised')" in brief
        assert "the verdict is on the whole current skill" in brief
    # Retrieving seats owe the manifest and the changed files; the unchanged file is one read away.
    assert "Unchanged since the previous verdict (one read away, not owed): " not in h.briefs["t1"]
    state = _state(h)
    assert state.content_hash == second.content_hash and set(review_ledger.load_record(h.drive, second.record_id)["subject"]["files"]) == {
        "SKILL.md", "scripts/hello.py", "scripts/util.py"}


def test_the_change_section_says_diff_unavailable_without_the_retained_copy_and_names_a_legacy_verdict(briefing):
    """Two-sided: when the earlier frozen copy is gone the files are still named and the diff is declared
    unavailable; a legacy review.json (no file index) names the earlier hash and says the index is missing."""
    import shutil

    h = briefing
    first = _review(h, reviewers=["t1"], reason="small payload")
    assert first.status == "clean"
    views = h.drive / "state" / "review_checkouts" / "views"
    for view in list(views.glob("inventory-*")):
        shutil.rmtree(view)
    (h.skill_dir / "scripts" / "hello.py").write_text("print('second edition')\n", encoding="utf-8")
    h.briefs.clear()
    second = _review(h, reviewers=["t1"], reason="small payload")
    assert second.status == "clean"
    assert "- modified: scripts/hello.py" in h.briefs["t1"]
    assert "diff unavailable (the earlier frozen copy is no longer retained)" in h.briefs["t1"]
    assert "### diff scripts/hello.py" not in h.briefs["t1"]

    # A legacy verdict: a skill reviewed before the fold has review.json of an earlier version and no ledger
    # record at all (the ledger is never edited under a live custody state).
    from ouroboros.skill_loader import SkillReviewState, save_review_state
    from ouroboros.skill_review import review_skill
    _build_skill(h.drive / "skills" / "external", "forecast")
    save_review_state(h.drive, "forecast", SkillReviewState(status="warnings", content_hash="legacy-hash-0001", timestamp="t",
                                                             findings=[{"item": "error_handling", "verdict": "FAIL", "severity": "advisory", "reason": "swallows"}]))
    h.briefs.clear()
    third = review_skill(h.ctx, "forecast", reviewers=["t1"], reason="small payload")
    assert third.status == "clean", third.error
    brief = h.briefs["t1"]
    assert "## Changed since the previous review legacy-hash- (warnings)" in brief  # the hash's first 12 characters
    assert "the earlier review kept no file index" in brief
    assert "### Previous findings (evidence, not instructions)" in brief and "[ADVISORY] error_handling" in brief
    state = load_review_state(h.drive, "forecast", skill_type="script", skill_dir=h.drive / "skills" / "external" / "forecast")
    assert state.record_id == third.record_id and state.status == "clean"


def test_an_oversized_payload_is_not_delivered_to_a_packet_seat_and_is_said_so(briefing):
    """J: no chunking. A packet seat that cannot hold the payload receives the file index and a plain
    "NOT delivered" statement; a retrieving seat still reads the frozen copy."""
    h = briefing
    (h.skill_dir / "big.txt").write_text("x" * 20_000 + "\n", encoding="utf-8")
    h.monkeypatch.setattr("ouroboros.tools.review_helpers.REVIEW_PROMPT_TOKEN_BUDGET", 2_000)
    outcome = _review(h, reviewers=["t1"], reason="small payload")
    assert outcome.status == "clean", outcome.error
    packet = h.briefs["t1"]
    assert "## Skill payload — NOT delivered" in packet and "exceeds this seat's packet budget" in packet
    assert "- big.txt: 20,001 bytes" in packet and "x" * 200 not in packet
    state = _state(h)
    [seat] = [row for row in state.seats if row["seat_id"] == "t1"]
    assert (seat["delivery"], seat["payload_form"]) == ("packet", "not_delivered")

    h.monkeypatch.setattr("ouroboros.tools.review_helpers.REVIEW_PROMPT_TOKEN_BUDGET", 920_000)
    (h.skill_dir / "big.txt").write_text("small now\n", encoding="utf-8")
    h.briefs.clear()
    again = _review(h, reviewers=["t1"], reason="small payload")
    assert again.status == "clean" and "## Skill payload — exact frozen copy" in h.briefs["t1"] and "small now" in h.briefs["t1"]
    [seat] = [row for row in _state(h).seats if row["seat_id"] == "t1"]
    assert seat["payload_form"] == "inline"


def test_a_deterministic_preflight_failure_stays_pending_and_dispatches_no_seat(harness):
    manifest = (harness.skill_dir / "SKILL.md").read_text(encoding="utf-8").replace(
        "  - name: hello.py\n", "  - name: hello.py\n  - name: absent.py\n    description: Missing.\n")
    (harness.skill_dir / "SKILL.md").write_text(manifest, encoding="utf-8")
    outcome = _review(harness, reviewers=["t1"], reason="small payload")
    assert outcome.status == "pending" and "skill_preflight failed" in outcome.error and harness.sends == []
    state = _state(harness)
    assert state.status == "pending" and state.findings[0]["item"] == "skill_preflight"
    assert state.gate_for(outcome.content_hash, enforcement="advisory")["executable_review"] is False
    assert state.gate_for(outcome.content_hash, enforcement="blocking")["executable_review"] is False


# --- the paid ceiling: the manual lane per content version, the tool lane per root task (owner Q23) ---------


def test_the_manual_lane_meets_the_ceiling_per_content_version(harness):
    """A Skills-page review has no task: the shared ceiling counts paid skill waves of these exact bytes; a
    byte-identical ask reuses the record (no wave bought), a rebuttal buys a new wave until the ceiling, and a
    revised payload starts a fresh count."""
    h = harness
    h.ctx.task_id = ""  # the manual lane (the Skills page, a Hub install)
    h.monkeypatch.setenv("OUROBOROS_REVIEW_MAX_CYCLES", "1")
    first = _review(h, reviewers=["t1"], reason="small payload")
    assert first.status == "clean" and first.paid and len(h.sends) == 1
    same = _review(h, reviewers=["t1"], reason="small payload")
    assert same.reused and len(h.sends) == 1
    rebutted = _review(h, reviewers=["t1"], reason="small payload", review_rebuttal="The finding cites a helper this skill does not call.")
    assert rebutted.status == "pending" and rebutted.dispatch_refusal_code == "LEGACY_BLOCKED" and len(h.sends) == 1
    assert "REVIEW_CYCLES_EXHAUSTED" in rebutted.error and "manual lane of skill weather" in rebutted.error
    assert _state(h).status == "clean", "the earlier verdict for these bytes stands"
    (h.skill_dir / "scripts" / "hello.py").write_text("print('revised')\n", encoding="utf-8")
    revised = _review(h, reviewers=["t1"], reason="small payload")
    assert revised.status == "clean" and revised.paid and len(h.sends) == 2


def test_the_tool_lane_shares_one_allowance_per_root_task_across_skills(harness):
    """A task's skill reviews (``task:<root>:<skill>`` groups) spend the ROOT's allowance of paid skill waves,
    whichever skill is reviewed; change and result reviews never use it up (their own tool names)."""
    h = harness
    h.monkeypatch.setenv("OUROBOROS_REVIEW_MAX_CYCLES", "1")
    _build_skill(h.drive / "skills" / "external", "forecast")
    h.ctx._skill_review_group_id = "task:task-skill:weather"
    first = _review(h, reviewers=["t1"], reason="small payload")
    assert first.status == "clean" and first.paid
    h.ctx._skill_review_group_id = "task:task-skill:forecast"
    from ouroboros.skill_review import review_skill

    second = review_skill(h.ctx, "forecast", reviewers=["t1"], reason="small payload")
    assert second.dispatch_refusal_code == "LEGACY_BLOCKED" and second.status == "pending" and len(h.sends) == 1
    h.ctx._skill_review_group_id = "task:another-root:forecast"
    third = review_skill(h.ctx, "forecast", reviewers=["t1"], reason="small payload")
    assert third.status == "clean" and third.paid and len(h.sends) == 2


# --- Cyber Pro: the panel composes freely and the review is evidence -----------------------------------------


@pytest.mark.parametrize("mode", ["advanced", "cyber_pro"])
def test_a_narrowed_panel_without_a_reason_is_refused_outside_cyber_pro(harness, mode):
    from ouroboros import config

    config.reset_runtime_mode_baseline_for_tests()
    config.initialize_runtime_mode_baseline(mode)
    try:
        outcome = _review(harness, reviewers=["t1"])
        if mode == "cyber_pro":
            assert outcome.status == "clean" and outcome.panel["assigned"] == ["t1"] and len(harness.sends) == 1
            assert _state(harness).gate_for(outcome.content_hash, enforcement="blocking")["executable_review"] is True
        else:
            assert outcome.dispatch_refusal_code == "TOOL_ARG_ERROR" and harness.sends == [] and outcome.status == "pending"
    finally:
        config.reset_runtime_mode_baseline_for_tests()


# --- the lifecycle surfaces: the Skills page, a Hub install, the owner's Skip, the author's finish -----------


def _lifecycle(harness, **kwargs):
    """The lifecycle runner as the Skills page and the tool call it (the lane job, the composed panel)."""
    from ouroboros.skill_review_runner import run_skill_review_lifecycle_blocking
    from tests.test_skill_review_runner import _reset_queue

    _reset_queue()
    try:
        return run_skill_review_lifecycle_blocking(harness.ctx, "weather", **kwargs)
    finally:
        _reset_queue()


def test_the_skills_page_review_is_the_same_wave_under_the_owner_panel_and_the_card_reads_the_record(harness):
    from ouroboros.skill_review_runner import skill_review_ui_projection

    payload = _lifecycle(harness, source="skills", reviewers=["t1"], reason="small payload")
    assert (payload["status"], payload["executable_review"], payload["paid"]) == ("clean", True, True), payload["error"]
    assert payload["record_id"] and payload["panel"]["chosen_by"] == "owner" and payload["panel"]["assigned"] == ["t1"]
    assert [send["slot_id"] for send in harness.sends] == ["t1"]
    record = review_ledger.load_record(harness.drive, payload["record_id"])
    facts = record["brief"]["skill"]
    assert (facts["source"], facts["job_id"], facts["group_id"]) == ("skills", payload["job_id"], "manual:weather")
    assert _state(harness).record_id == payload["record_id"]
    projection = skill_review_ui_projection(harness.drive, "weather")
    [row] = projection["history"]
    assert (row["record_id"], row["status"], row["job_id"], row["source"]) == (payload["record_id"], "clean", payload["job_id"], "skills")
    assert row["panel"]["assigned"] == ["t1"] and row["executions"]


def test_a_hub_install_reviews_in_the_background_and_settles_the_kept_update_after_the_wave(harness):
    """``start_review`` (a Hub install, ``check=review``): the same wave on a background thread under the
    marketplace context; the kept update snapshot is settled only once the wave is over, with the digest
    the install record named."""
    import threading

    from ouroboros import skill_source_install as install

    settled = []
    harness.monkeypatch.setattr(install, "read_install_record", lambda drive, name: {"release": {"digest": "sha256:feed"}})
    harness.monkeypatch.setattr(install, "settle_pending_update",
                                lambda drive, name, **kw: settled.append((name, kw, _state(harness).status)) or {"status": "settled"})
    backup = install.update_backup_path(harness.drive, "weather")
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text("{}", encoding="utf-8")
    from tests.test_skill_review_runner import _reset_queue

    _reset_queue()
    try:
        install.start_review(harness.drive, "weather", repo_dir=harness.system, reviewers=["t1"], reason="small payload")
        [thread] = [t for t in threading.enumerate() if t.name == "skill-install-review-weather"]
        thread.join(120)
        assert not thread.is_alive()
    finally:
        _reset_queue()
    state = _state(harness)
    assert state.status == "clean" and state.record_id and state.panel["chosen_by"] == "owner"
    assert [send["slot_id"] for send in harness.sends] == ["t1"]
    # The lifecycle settles the kept update once the verdict is in (the job's own digest), and the install's
    # finally-clause settles again with the record's digest while the snapshot is still kept: both after the verdict.
    assert settled and all(status == "clean" for _name, _kw, status in settled)
    assert settled[-1] == ("weather", {"expected_digest": "sha256:feed"}, "clean")
    record = review_ledger.load_record(harness.drive, state.record_id)
    assert record["brief"]["skill"]["source"] == "skills" and record["task_id"] == "marketplace_install"


def test_the_owner_skip_attests_the_bytes_without_a_wave_and_publication_still_wants_the_full_review(harness):
    from ouroboros.skill_owner_attestation import review_skill_owner_attest
    from ouroboros.skill_publish_eligibility import submit_hub_eligibility

    payload = _lifecycle(harness, source="skills", owner_attestation=True, review_impl=review_skill_owner_attest)
    assert (payload["status"], payload["review_profile"]) == ("clean", "owner_attested"), payload["error"]
    assert harness.sends == [] and review_ledger.recent_records(harness.drive, "", surface="skill") == []
    state = _state(harness)
    assert state.review_profile == "owner_attested" and state.record_id == ""
    assert (harness.drive / "state" / "skills" / "weather" / "owner_attestation.json").is_file()
    assert state.gate_for(state.content_hash, enforcement="blocking")["executable_review"] is True
    eligibility = submit_hub_eligibility(source="external", review_status=state.status, review_profile=state.review_profile,
                                         github_token_configured=True)
    assert eligibility["reason"] == "Owner-attested skills need a full LLM review before publication"


@pytest.mark.parametrize("enforcement", ["advisory", "blocking"])
def test_an_author_finish_after_an_edit_binds_the_new_bytes_in_advisory_and_is_refused_in_blocking(harness, enforcement):
    """The author answers the reviewer's warning by editing and finishing: Advisory records the acceptance for
    the NEW bytes against the retained reviewer evidence (no second panel); Blocking refuses the finish."""
    from ouroboros.tool_access_types import ResolvedResourceBinding
    from ouroboros.tools import skill_exec

    h = harness
    h.answers["t1"] = SOFT
    first = _review(h, reviewers=["t1"], reason="small payload")
    assert first.status == "warnings"
    (h.skill_dir / "scripts" / "hello.py").write_text("print('handled')\n", encoding="utf-8")
    h.monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", enforcement)
    binding = ResolvedResourceBinding(profile="self_modification", root="skill_payload", operation="review",
                                      base_path=h.skill_dir, target_path=h.skill_dir, source="test",
                                      skill_name="weather", state_drive_root=h.drive)
    finished = skill_exec._author_finish_existing_skill_review(
        h.ctx, binding, "weather", disposition="accepted", rationale="The exception is handled now; verified locally.")
    assert len(h.sends) == 1, "a finish never buys a panel"
    state = _state(h)
    if enforcement == "blocking":
        assert "explicit author finish requires advisory enforcement" in finished["error"]
        assert not state.author_disposition and state.content_hash == first.content_hash
        return
    assert "error" not in finished and finished["record_id"] == first.record_id
    assert finished["content_hash"] != first.content_hash and finished["reviewed_content_hash"] == first.content_hash
    assert state.author_disposition["disposition"] == "accepted" and state.author_disposition["subject_hash"] == finished["content_hash"]
    assert [f["item"] for f in state.findings] == ["error_handling"], "the reviewer's evidence stays"
    gate = state.gate_for(finished["content_hash"], enforcement="advisory")
    assert gate["executable_review"] is True and gate["blocking_reason"] == "author_accepted_advisory"


# --- the receptive author, publication, and the silo between skill and repo review -------------------------


def test_the_tool_author_hears_mail_while_the_wave_runs_and_a_left_wave_is_reissued_by_name(harness):
    """The ``skill_review`` tool binds the receptive author around the lifecycle call (an addressed message
    may end the wait; the wave goes on) and the left-wave watch names the exact re-issue; a caller without a
    continuation owner keeps the synchronous wait."""
    import contextlib

    from ouroboros import review_pause
    from ouroboros.tools import skill_exec
    from tests.test_skill_review_runner import _reset_queue

    h = harness
    h.ctx.owner_wait_callback = lambda *_a, **_k: "parked"
    h.ctx.task_attempt = 1
    bindings, watched = [], []
    real_author = review_pause.receptive_author

    @contextlib.contextmanager
    def recording(binding):
        bindings.append(binding)
        with real_author(binding) as bound:
            yield bound

    h.monkeypatch.setattr(review_pause, "receptive_author", recording)
    h.monkeypatch.setattr(review_pause, "watch_left_review", lambda ctx, **kwargs: watched.append(kwargs))
    h.monkeypatch.setattr(skill_exec, "_skill_tool_preflight", lambda *a, **k: "")
    _reset_queue()
    try:
        text = skill_exec._handle_review_skill(h.ctx, skill="weather", reviewers=["t1"], reason="small payload")
    finally:
        _reset_queue()
    assert [send["slot_id"] for send in h.sends] == ["t1"] and "Review reference: " in text
    reference = json.loads(text.rsplit("Review reference: ", 1)[1])
    assert reference["record_id"] == _state(h).record_id and reference["content_hash"] == _state(h).content_hash
    [binding] = bindings
    assert binding and binding["task_id"] == "task-skill" and binding["drive_root"] == h.drive
    [kwargs] = watched
    assert kwargs["surface"] == "skill" and kwargs["record_id"] == reference["record_id"]
    assert kwargs["reissue"] == "the same unchanged skill_review(skill='weather') call"
    assert review_pause._LEFT_TOOLS["skill"] == "review_skill" and review_pause._LEFT_SURFACES["skill"] == "skill"
    assert review_pause.receptive_binding(SimpleNamespace(drive_root=h.drive, task_id="task-skill")) is None


def test_publication_reads_the_projected_verdict_fresh_stale_or_blocked(harness):
    from ouroboros.skill_loader import find_skill
    from ouroboros.skill_publish_eligibility import submit_hub_eligibility

    h = harness

    def eligibility():
        skill = find_skill(h.drive, "weather", repo_path="")
        state = _state(h)
        return submit_hub_eligibility(source="external", review_status=state.status, review_profile=state.review_profile,
                                      review_stale=state.is_stale_for(skill.content_hash), github_token_configured=True)

    assert _review(h, reviewers=["t1"], reason="small payload").status == "clean"
    assert eligibility()["reason"] == "Open Publish to check the current bytes before publication"
    (h.skill_dir / "scripts" / "hello.py").write_text("print('edited')\n", encoding="utf-8")
    assert eligibility()["reason"] == "Skill needs a fresh review before publication"
    h.answers["t1"] = HARD
    assert _review(h, reviewers=["t1"], reason="small payload").status == "blockers"
    assert eligibility()["reason"] == "Skill needs review work before publication"


def test_a_skill_record_creates_no_repo_review_debt_and_a_repo_record_no_skill_verdict(harness):
    """CHECKLISTS "Skill review vs. repo review", both directions: the paid skill wave is invisible to every
    repo-side reader (the commit gate's cycles, the change lane, the gate surfaces of the ledger), and a repo
    record is invisible to every skill-side reader (the skill's records, its earlier verdict, the task's skills)."""
    from ouroboros.review_state import load_state
    from ouroboros.skill_readiness import _skill_names_from_review_history
    from ouroboros.tools import commit_gate
    from ouroboros.tools.review_change_custody import review_state_root
    from ouroboros.tools.review_skill import earlier_verdict, skill_record_rows
    from ouroboros.skill_loader import find_skill
    from tests.test_review_ledger import _facts, _raw

    h = harness
    h.ctx._skill_review_group_id = "task:task-skill:weather"
    outcome = _review(h, reviewers=["t1"], reason="small payload")
    assert outcome.paid and outcome.status == "clean"
    for surface in ("commit_gate", "change", "result", "preflight"):
        assert review_ledger.recent_records(h.drive, "task-skill", surface=surface) == [], surface
    attempts = load_state(review_state_root(h.ctx))
    assert [row.tool_name for row in attempts.filter_attempts(tool_name="review_skill") if row.paid] == ["review_skill"]
    for tool in ("commit_reviewed", "review_change", "review_result"):
        assert attempts.filter_attempts(tool_name=tool) == []
        h.ctx._current_review_tool_name = tool
        assert commit_gate.count_paid_review_cycles(h.ctx, root_task_id="task-skill") == 0, tool
    h.ctx._current_review_tool_name = "review_skill"
    assert commit_gate.count_paid_review_cycles(h.ctx, root_task_id="task-skill") == 1

    repo = review_ledger.build_wave_record(_facts([_raw("s1", "openai/gpt-5")], task_id="task-skill"),
                                           surface="commit_gate", drive_root=h.drive)
    review_ledger.write_record(h.drive, repo)
    assert [row["record_id"] for row in review_ledger.recent_records(h.drive, "task-skill", surface="commit_gate")] == [repo.record_id]
    assert [row["record_id"] for row in skill_record_rows(h.drive, "weather")] == [outcome.record_id]
    assert earlier_verdict(h.drive, find_skill(h.drive, "weather", repo_path=""))["record_id"] == outcome.record_id
    assert _skill_names_from_review_history(h.drive, "task-skill")["names"] == ["weather"]
