"""The issue tools' two-step sends tell the truth about the step that failed and keep the identity of what was created.

Paired with their earlier behaviour through the real transport over a fake ``subprocess.run``: a label step that
failed used to vanish behind "✅ Issue created", and a failed closing comment used to return a bare transport error
that said nothing about the close that was never sent. Success paths keep their text and call counts.
"""

import subprocess
from types import SimpleNamespace

import pytest

from ouroboros.tools import github
from tests.test_github_project_target import _context

URL = "https://github.com/owner/selected/issues/7"
_REFUSED = ("gh: Validation Failed (HTTP 422)\n", 1)


@pytest.fixture
def gh(monkeypatch):
    """A gh whose answers are chosen per subcommand: ``behaviour[("issue", "edit")] = (stdout, stderr, returncode)``."""
    monkeypatch.setattr(github, "github_token_from_env_or_settings", lambda: "fixture-token")
    state = SimpleNamespace(calls=[], behaviour={})

    def run(argv, **kwargs):
        state.calls.append(argv)
        answer = state.behaviour.get(tuple(argv[1:3]), (URL if argv[1:3] == ["issue", "create"] else "", "", 0))
        if answer == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        stdout, stderr, code = answer
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", run)
    return state


@pytest.fixture
def ctx(tmp_path):
    context, _project = _context(tmp_path, "queued")
    context._active_builtin_tool_result = None
    return context


def _typed(ctx):
    return ctx._active_builtin_tool_result


def _sent(state):
    return [argv[1:3] for argv in state.calls]


# --- create_github_issue with labels --------------------------------------------------------------------------------------

def test_create_with_labels_keeps_the_created_identity_when_labelling_is_refused(gh, ctx):
    gh.behaviour[("issue", "edit")] = ("", *_REFUSED)
    text = github._create_issue(ctx, "Title", "Body", labels="bug,urgent")
    assert _sent(gh) == [["issue", "create"], ["issue", "edit"]], "one create, one label request, no retry"
    assert text == (f"⚠️ PARTIAL_EFFECT: issue #7 created: {URL} — labels 'bug,urgent' are not confirmed: the label request ended "
                    "with exit 1, HTTP 422: ⚠️ GH_ERROR: gh: Validation Failed (HTTP 422). Do not create the issue again; add the "
                    "labels to #7.")
    assert (_typed(ctx).status, _typed(ctx).code) == ("error", "TOOL_ERROR")
    assert "operation_outcome" not in _typed(ctx).meta, "an effect happened: no no-effect attestation"


def test_create_with_labels_names_an_unknown_label_outcome_after_a_timeout(gh, ctx):
    gh.behaviour[("issue", "edit")] = "timeout"
    text = github._create_issue(ctx, "Title", "", labels="bug")
    assert text == (f"⚠️ PARTIAL_EFFECT: issue #7 created: {URL} — labels 'bug' are not confirmed: the label request timed out: "
                    "⚠️ GH_TIMEOUT: exceeded 30s.. Do not create the issue again; add the labels to #7.")


def test_create_answer_without_an_issue_number_sends_no_label_request_and_says_so(gh, ctx):
    gh.behaviour[("issue", "create")] = ("created", "", 0)
    text = github._create_issue(ctx, "Title", "", labels="bug")
    assert _sent(gh) == [["issue", "create"]]
    assert text == ("⚠️ PARTIAL_EFFECT: issue created: created — labels 'bug' were not requested: the create answer named no "
                    "issue number. Do not create the issue again; add the labels to the issue at that URL.")


def test_create_success_paths_are_unchanged(gh, ctx):
    assert github._create_issue(ctx, "Title", "Body", labels="bug") == f"✅ Issue created: {URL}"
    assert _sent(gh) == [["issue", "create"], ["issue", "edit"]]
    assert gh.calls[1][1:] == ["issue", "edit", "7", "--add-label=bug", "--repo", ""] or gh.calls[1][1:5] == ["issue", "edit", "7", "--add-label=bug"]
    gh.calls.clear()
    assert github._create_issue(ctx, "Title") == f"✅ Issue created: {URL}"
    assert _sent(gh) == [["issue", "create"]]
    gh.behaviour[("issue", "create")] = ("", *_REFUSED)
    assert github._create_issue(ctx, "Title", labels="bug") == "⚠️ GH_ERROR: gh: Validation Failed (HTTP 422)"


# --- close_github_issue with a comment --------------------------------------------------------------------------------------

def test_close_whose_comment_is_refused_sends_no_close_and_says_the_issue_stays_open(gh, ctx):
    gh.behaviour[("issue", "comment")] = ("", *_REFUSED)
    text = github._close_issue(ctx, 7, comment="Fixed in #8")
    assert _sent(gh) == [["issue", "comment"]]
    assert text == ("⚠️ TOOL_ERROR: the closing comment request for issue #7 ended with exit 1, HTTP 422: ⚠️ GH_ERROR: gh: Validation "
                    "Failed (HTTP 422). Whether the comment was posted is not confirmed; the close request was not sent, so this "
                    "call did not close the issue.")
    assert (_typed(ctx).status, _typed(ctx).code) == ("error", "TOOL_ERROR")


def test_close_whose_comment_timed_out_names_the_unknown_comment_and_the_unsent_close(gh, ctx):
    gh.behaviour[("issue", "comment")] = "timeout"
    text = github._close_issue(ctx, 7, comment="Fixed")
    assert _sent(gh) == [["issue", "comment"]]
    assert text.startswith("⚠️ TOOL_ERROR: the closing comment request for issue #7 timed out: ⚠️ GH_TIMEOUT: exceeded 30s.. Whether "
                           "the comment was posted is not confirmed; the close request was not sent")


def test_close_refused_after_the_comment_went_through_reports_the_partial_effect(gh, ctx):
    gh.behaviour[("issue", "close")] = ("", *_REFUSED)
    text = github._close_issue(ctx, 7, comment="Fixed")
    assert _sent(gh) == [["issue", "comment"], ["issue", "close"]]
    assert text == ("⚠️ PARTIAL_EFFECT: the closing comment was added to issue #7, but the close request ended with exit 1, HTTP 422: "
                    "⚠️ GH_ERROR: gh: Validation Failed (HTTP 422). Whether the issue is closed is not confirmed; closing it again "
                    "without `comment` sends no second comment.")
    assert (_typed(ctx).status, _typed(ctx).code) == ("error", "TOOL_ERROR") and "operation_outcome" not in _typed(ctx).meta


def test_close_without_a_comment_keeps_the_bare_transport_error_and_text(gh, ctx):
    gh.behaviour[("issue", "close")] = ("", *_REFUSED)
    assert github._close_issue(ctx, 7) == "⚠️ GH_ERROR: gh: Validation Failed (HTTP 422)"
    gh.behaviour.clear()
    assert github._close_issue(ctx, 7) == "✅ Issue #7 closed."
    assert github._close_issue(ctx, 7, comment="Fixed") == "✅ Issue #7 closed. The closing comment was added."


def test_close_target_refusal_before_any_launch_passes_through_typed(gh, ctx):
    ctx.task_metadata = {"_project_room_note": "registry unavailable"}
    ctx.workspace_root = None
    ctx.is_direct_chat = True
    text = github._close_issue(ctx, 7, comment="Fixed", repo="")
    assert "GH_TARGET_UNAVAILABLE" in text and gh.calls == []


# --- deltas the parent integrates (fails loudly once they land, so this marker is removed with them) ---------------------

NEW_READERS = ("get_github_run_log", "list_github_run_artifacts", "download_github_artifact")
NEW_WRITERS = ("create_github_pr", "update_github_pr", "set_github_pr_ready")


def test_github_workflow_inventory_and_authority_memberships():
    from ouroboros.tool_capabilities import OBSERVE_WORLD_MUTATION_TOOLS
    from ouroboros.tools.registry_guards import _GITHUB_TOKEN_TOOLS
    from tests.test_smoke import EXPECTED_TOOLS

    assert set(NEW_READERS + NEW_WRITERS) <= _GITHUB_TOKEN_TOOLS
    assert set(NEW_WRITERS) <= OBSERVE_WORLD_MUTATION_TOOLS
    assert set(NEW_READERS + NEW_WRITERS) <= set(EXPECTED_TOOLS)
