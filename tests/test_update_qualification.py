"""Qualification is portable evidence of the exact proposed range, never a veto."""
import json

import pytest

from ouroboros import update_letter as letter, update_qualification as qualification
from ouroboros.tools import github
from tests.test_pr_merge_receipts import BASE, HEAD, _receipts, world  # noqa: F401
from tests.test_update_letter import _capture_for, _commit, _git, _record, _status, history_repo  # noqa: F401


@pytest.mark.parametrize("state", ["passed", "failed", "not_run"])
def test_merge_commit_carries_checks_and_missing_evidence_without_blocking(world, state):  # noqa: F811
    checks = [{"name": "full_battery", "status": state, "detail": "exact candidate"}]
    out = github._pr_merge(world.ctx, number=7, expected_head_sha=HEAD, method="merge", checks=checks,
                           review_verdict="AUTHOR ACCEPTED")
    assert "merge: merged" in out
    call = next(c for c in world.gh.calls if c[:2] == ["pr", "merge"])
    body = call[call.index("--body") + 1]
    receipt = qualification.commit_qualification(body)
    assert receipt == _receipts(world)[0]["qualification"]
    assert receipt["checks"][0] == {**checks[0], "source": "author_declared"}
    assert receipt["checks"][1]["name"] == "cost_contract"
    assert receipt["checks"][1]["status"] == "unknown"
    assert "No execution evidence" in body and "Post-merge check: not run yet" in body
    assert receipt["review"] == {"observed": "unknown", "declared": "AUTHOR ACCEPTED"}
    assert "Summary of the change" in body


def test_rebase_discloses_that_it_creates_no_merge_commit(world):  # noqa: F811
    github._pr_merge(world.ctx, number=7, expected_head_sha=HEAD, method="rebase")
    assert _receipts(world)[0]["commit_receipt"] == "no_merge_commit_for_rebase"
    assert "--body" not in next(c for c in world.gh.calls if c[:2] == ["pr", "merge"])


def test_check_shape_refusal_then_valid_missing_checks_still_merge(world):  # noqa: F811
    out = github._pr_merge(world.ctx, number=7, expected_head_sha=HEAD, method="squash", checks=[{}])
    assert "TOOL_ARG_ERROR" in out and not world.gh.calls
    assert "merge: merged" in github._pr_merge(world.ctx, number=7, expected_head_sha=HEAD, method="squash")


def test_malformed_trailer_is_unknown_and_valid_one_is_read():
    receipt = qualification.merge_qualification({}, [{"name": "full_battery", "status": "passed"}])
    for changes in ({"checks": [None]}, {"checks": [{"name": "full_battery", "status": "maybe"}]}, {"review": []}):
        body = qualification.TRAILER + json.dumps({**receipt, **changes})
        assert qualification.commit_qualification(body) is None
    assert qualification.commit_qualification(qualification.commit_summary(receipt)) == receipt


def test_github_checks_include_red_intermediate_sha_but_exclude_other_ranges():
    commits = [{"sha": "a"}, {"sha": "b"}]
    runs = [{"head_sha": sha, "conclusion": result, "status": "completed", "html_url": f"https://github.com/r/{sha}"}
            for sha, result in (("b", "success"), ("a", "failure"), ("outside", "failure"))]
    urls = []
    def get(url):
        urls.append(url)
        return {"workflow_runs": runs}
    fact = qualification.post_merge_checks(commits, "https://github.com/owner/repo.git", get_json=get)
    assert [(r["sha"], r["conclusion"]) for r in fact["runs"]] == [("b", "success"), ("a", "failure")]
    assert fact["status"] == "observed" and fact["missing_shas"] == []
    assert len(urls) == 1 and "/actions/workflows/post-merge.yml/runs?" in urls[0]
    empty = qualification.post_merge_checks(commits, "https://github.com/owner/repo", get_json=lambda _: {"workflow_runs": []})
    assert empty["missing_shas"] == ["a", "b"] and not empty["runs"]
    unavailable = qualification.post_merge_checks(commits, "https://github.com/owner/repo",
                                                   get_json=lambda _: (_ for _ in ()).throw(OSError()))
    assert unavailable["status"] == "unavailable" and not unavailable["runs"]


def test_preflight_uses_exact_real_git_range_and_names_unqualified_items(history_repo, tmp_path, monkeypatch):  # noqa: F811
    from ouroboros import server_process
    monkeypatch.setattr(server_process, "server_source_baseline", lambda: "running-source")
    repo, base, old = history_repo["repo"], history_repo["base"], history_repo["c4"]
    checks = [{"name": "full_battery", "status": "failed", "detail": "Author accepted two FAILs"},
              {"name": "cost_contract", "status": "not_run"}]
    receipt = qualification.merge_qualification({"declared": {"verdict": "AUTHOR ACCEPTED"}}, checks)
    (repo / "qualification.txt").write_text("candidate", encoding="utf-8")
    target = _commit(repo, "Incoming qualification\n\n" + qualification.commit_summary(receipt))
    monkeypatch.setattr(letter, "_default_git", lambda: _capture_for(repo))
    monkeypatch.setattr(qualification, "post_merge_checks", lambda commits, _: {
        "status": "observed", "runs": [{"sha": target, "conclusion": "failure", "url": "https://github.com/run/1"}]})
    drive = tmp_path / "letter"
    letter.atomic_write_json(letter.record_path(drive), _record(key={**_record()["key"], "base_sha": base, "target_sha": old}))
    prompts = []
    def write(status, material, **kwargs):
        prompts.append(letter._request_text(status, material, "1"))
        return _record(key=letter._key_from_status(status), text="Incoming qualification has accepted FAILs.")
    monkeypatch.setattr(letter, "write_letter", write)
    result = qualification.preflight_description({"base_sha": base, "target_sha": target,
                                                  "update_channel": "stable", "target_ref": "managed/main"}, drive_root=drive)
    assert result["letter"]["key"]["target_sha"] == target and result["letter"]["description_current"]
    assert result["qualification"]["target_sha"] == target
    assert {c["sha"] for c in result["qualification"]["commits"]} == set(_git(repo, "rev-list", f"{base}..{target}").splitlines())
    assert all(word in prompts[0] for word in (target, "Author accepted two FAILs", '"conclusion": "failure"', "not_run"))
    assert '"sha": "running-source"' in prompts[0] and f'"base_sha": "{base}"' in prompts[0]
    # Green evidence stays green; host code does not invent a failure from prose.
    green = qualification.merge_qualification({"record": {"verdict": {"aggregate": "PASS"}}},
        [{"name": name, "status": "passed"} for name in qualification.CHECKS])
    assert all(row["status"] == "passed" for row in green["checks"])
    assert qualification.commit_qualification("No tests failed according to this prose") is None


def test_new_post_merge_red_refreshes_same_range_and_offline_never_becomes_green(tmp_path, monkeypatch):
    base, target = "a" * 40, "b" * 40
    material = {"base_sha": base, "target_sha": target, "commits": [{"sha": target, "subject": "change", "body": ""}]}
    monkeypatch.setattr(letter, "collect_range_material", lambda *a: dict(material))
    monkeypatch.setattr(letter, "_default_git", lambda: lambda _: (1, "", ""))
    observed = {"status": "observed", "runs": [{"sha": target, "conclusion": "success"}]}
    monkeypatch.setattr(qualification, "post_merge_checks", lambda *a: dict(observed))
    calls = []
    def write(status, material, **kwargs):
        calls.append(material["qualification"])
        return _record(text=f"letter {len(calls)}")
    monkeypatch.setattr(letter, "write_letter", write)
    for _ in range(2):
        letter.refresh_after_check(_status(), drive_root=tmp_path)
    assert len(calls) == 1
    observed["runs"] = [{"sha": target, "conclusion": "failure"}]
    letter.refresh_after_check(_status(), drive_root=tmp_path)
    assert len(calls) == 2 and calls[-1]["github"]["runs"][0]["conclusion"] == "failure"
    observed.update(status="unavailable", runs=[])
    letter.refresh_after_check(_status(), drive_root=tmp_path)
    assert len(calls) == 3 and calls[-1]["github"]["status"] == "unavailable"
    assert json.loads(letter.record_path(tmp_path).read_text(encoding="utf-8"))["text"] == "letter 3"


def test_failed_preflight_letter_does_not_show_prior_range(tmp_path, monkeypatch):
    old = _record()
    monkeypatch.setattr(letter, "refresh_after_check", lambda *a, **k: old)
    result = qualification.preflight_description({"base_sha": "a" * 40, "target_sha": "c" * 40}, drive_root=tmp_path)
    assert result["letter"]["text"] == "" and result["letter"]["description_current"] is False
    result = qualification.preflight_description({"base_sha": "a" * 40, "target_sha": "b" * 40}, drive_root=tmp_path)
    assert result["letter"]["text"] == "letter" and result["letter"]["description_current"]


@pytest.mark.parametrize("failure", ["author", "material_read"])
def test_failed_same_range_rewrite_keeps_new_red_facts_but_marks_old_prose_stale(tmp_path, monkeypatch, failure):
    base, target = "a" * 40, "b" * 40
    green = {"base_sha": base, "target_sha": target, "commits": [{"sha": target, "subject": "change"}],
             "github": {"status": "observed", "runs": [{"sha": target, "conclusion": "success"}]}}
    red = {"status": "observed", "runs": [{"sha": target, "conclusion": "failure"}]}
    letter.atomic_write_json(letter.record_path(tmp_path), _record(qualification=green, text="Old green description"))
    monkeypatch.setattr(qualification, "post_merge_checks", lambda *a: red)
    monkeypatch.setattr(letter, "_default_git", lambda: lambda _: (1, "", ""))
    def collect(*args):
        if failure == "material_read":
            raise letter.MaterialUnavailable("Git object unavailable")
        return {**green, "commits": [{"sha": target, "subject": "change", "body": ""}]}
    monkeypatch.setattr(letter, "collect_range_material", collect)
    monkeypatch.setattr(letter, "write_letter", lambda *a, **k: _record(state="failed", text="", error_kind="budget_exhausted"))
    failed = qualification.preflight_description({"base_sha": base, "target_sha": target,
        "update_channel": "stable", "target_ref": "managed/main"}, drive_root=tmp_path)
    assert failed["letter"]["description_current"] is False and failed["letter"]["text"] == ""
    assert failed["qualification"]["github"] == red
    # A later successful author consumes the new evidence and becomes current.
    failure = ""
    monkeypatch.setattr(letter, "write_letter", lambda *a, **k: _record(text="This merge has a red check"))
    fixed = qualification.preflight_description({"base_sha": base, "target_sha": target,
        "update_channel": "stable", "target_ref": "managed/main"}, drive_root=tmp_path)
    assert fixed["letter"]["description_current"] and fixed["letter"]["text"] == "This merge has a red check"
