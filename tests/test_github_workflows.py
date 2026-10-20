"""The workflow-run readers behind ``get_github_run_log``, ``list_github_run_artifacts`` and ``download_github_artifact``.

Exercise exact captured bytes, source identity, retained reads and negative controls. A valid shell
command can preserve bytes or fetch an artifact by id too; these tests make no claim that a shell
alternative cannot provide the same facts, or that model latency has improved.
"""

import hashlib
import io
import json
import pathlib
import subprocess
import zipfile
from types import SimpleNamespace

import pytest

from ouroboros.artifacts import task_artifact_dir_path
from ouroboros.tool_access import canonical_data_root
from ouroboros.tools import github, github_workflows
from tests.test_github_project_target import BASE, SHA, _context

LOG = b"test\tRun pytest\t2026-10-20T10:00:00Z FAILED tests/test_x.py::test_y\r\ntest\tRun pytest\t=== 1 failed ===\r\n"
OTHER = "https://github.example/other/thing"


def _answer(payload):
    return github.GhResult(True, json.dumps(payload), 0, None, "")


def _zip(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _capture(path, data, cap):
    """What the transport's exact branch leaves behind: the first ``cap`` bytes, hashed as written."""
    kept = data[:cap]
    pathlib.Path(path).write_bytes(kept)
    truncated = len(data) > cap
    return github.GhResult(True, "", None if truncated else 0, None, "",
                           github.GhCapture(pathlib.Path(path), len(kept), hashlib.sha256(kept).hexdigest(), truncated))


class FakeGh:
    """GitHub's answers about runs and artifacts; every call is recorded with its transport binding and cap."""

    def __init__(self, *, run=None, log=LOG, artifacts=(), artifact=None, archive=b"", repo_url=BASE, failing=None, total=None):
        self.run = run if run is not None else {"databaseId": 11, "url": f"{BASE}/actions/runs/11", "status": "completed",
                                                "conclusion": "failure", "attempt": 1, "headSha": SHA, "workflowName": "CI",
                                                "jobs": [{"databaseId": 55, "name": "test", "status": "completed",
                                                          "conclusion": "failure", "url": f"{BASE}/actions/runs/11/job/55"}]}
        self.log, self.artifacts, self.artifact, self.archive, self.repo_url = log, list(artifacts), artifact, archive, repo_url
        self.failing, self.calls, self.total = failing or {}, [], total

    def __call__(self, args, ctx, timeout=30, input_data=None, *, repo=github._GENERIC_TRANSPORT, capture_to=None, max_bytes=0):
        self.calls.append(SimpleNamespace(args=list(args), repo=repo, timeout=timeout, capture_to=capture_to, max_bytes=max_bytes))
        kind = self.kind(args, capture_to)
        if kind in self.failing:
            return self.failing[kind]
        if kind == "run_json":
            return _answer(self.run)
        if kind == "log":
            return _capture(capture_to, self.log, max_bytes)
        if kind == "repo":
            return _answer({"nameWithOwner": "/".join(self.repo_url.split("/")[-2:]), "url": self.repo_url})
        if kind == "artifacts":
            return _answer({"total_count": len(self.artifacts) if self.total is None else self.total, "artifacts": self.artifacts})
        if kind == "artifact":
            return _answer(self.artifact)
        return _capture(capture_to, self.archive, max_bytes)

    @staticmethod
    def kind(args, capture_to):
        if args[:2] == ["run", "view"]:
            return "log" if capture_to is not None else "run_json"
        if args[:2] == ["repo", "view"]:
            return "repo"
        if args[0] == "api":
            return "zip" if args[1].endswith("/zip") else "artifacts" if "/runs/" in args[1] else "artifact"
        raise AssertionError(args)

    def kinds(self):
        return [self.kind(call.args, call.capture_to) for call in self.calls]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(github, "github_token_from_env_or_settings", lambda: "fixture-token")

    def install(**kwargs):
        gh = FakeGh(**kwargs)
        monkeypatch.setattr(github_workflows, "_gh_run", gh)
        return gh
    return install


@pytest.fixture
def ctx(tmp_path):
    context, _project = _context(tmp_path, "queued")
    context._active_builtin_tool_result = None  # Handler-level calls publish their typed result here.
    return context


def _retained(ctx, text):
    """The retained file a result names, read from this task's artifact store."""
    path = text.split("Retained: artifact_store/", 1)[1].split(" ", 1)[0]
    return task_artifact_dir_path(canonical_data_root(ctx), "task-fixture") / path


def _typed(ctx):
    return ctx._active_builtin_tool_result


# --- get_github_run_log ---------------------------------------------------------------------------------------------

def test_run_log_resolves_identity_retains_exact_bytes_and_shows_the_tail(fake, ctx):
    """Paired benefit over ``gh run view 11 --log`` read as text: one call names the repository, attempt, source command
    and exact byte count, retains the bytes with their sha256 at a read_file address, and shows the tail."""
    gh = fake()

    text = github_workflows.get_run_log(ctx, run_id=11, repo="")

    assert gh.kinds() == ["run_json", "log"]
    assert gh.calls[1].args == ["run", "view", "11", "--log", "--attempt", "1"], "pinned to the attempt the metadata read observed"
    assert gh.calls[1].repo == "" and gh.calls[1].max_bytes == github_workflows.LOG_MAX_BYTES_DEFAULT
    assert text.startswith("GitHub Actions log — owner/selected run 11 attempt 1\n")
    assert f"Source: gh run view 11 --log --attempt 1; captured {len(LOG)} bytes exactly\n" in text
    assert hashlib.sha256(LOG).hexdigest() in text
    assert _retained(ctx, text).read_bytes() == LOG, "the retained file holds the bytes as captured, CRLF and final newline included"
    assert "Lines: 2; showing the last 2" in text
    assert text.endswith("---\n" + LOG.decode().replace("\r\n", "\n").rstrip("\n"))
    assert (_typed(ctx).status, _typed(ctx).code, _typed(ctx).meta["operation_outcome"]) == ("ok", "OK", "completed_no_effect")


def test_run_log_job_validates_membership_and_reads_by_job_id(fake, ctx):
    gh = fake()
    text = github_workflows.get_run_log(ctx, run_id=11, job_id=55, failed_only=True, repo="github.example/owner/selected")
    assert gh.calls[1].args == ["run", "view", "--log-failed", "--job", "55", "--attempt", "1"]
    assert gh.calls[1].repo == "github.example/owner/selected"
    assert text.startswith("GitHub Actions log — owner/selected run 11 attempt 1, job 55 test (failure)\n")


def test_run_log_refuses_a_job_outside_the_run_before_any_download(fake, ctx):
    gh = fake()
    text = github_workflows.get_run_log(ctx, run_id=11, job_id=99)
    assert gh.kinds() == ["run_json"]
    assert text == "⚠️ TOOL_ARG_ERROR: job 99 is not a job of run 11 attempt 1 in owner/selected; its jobs: 55 test."
    assert (_typed(ctx).status, _typed(ctx).code) == ("error", "TOOL_ARG_ERROR")


def test_run_log_of_an_unfinished_run_is_refused_without_a_download(fake, ctx):
    gh = fake(run={"databaseId": 11, "url": f"{BASE}/actions/runs/11", "status": "in_progress", "attempt": 1, "jobs": []})
    text = github_workflows.get_run_log(ctx, run_id=11)
    assert gh.kinds() == ["run_json"]
    assert text == ("⚠️ TOOL_ERROR: run 11 attempt 1 in owner/selected is in_progress; GitHub serves the log of a completed run "
                    "only, so no log was requested.")


def test_run_log_attempt_is_read_and_passed_to_the_capture(fake, ctx):
    gh = fake(run={"databaseId": 11, "url": f"{BASE}/actions/runs/11", "status": "completed", "conclusion": "success",
                   "attempt": 2, "headSha": SHA, "workflowName": "CI", "jobs": []})
    text = github_workflows.get_run_log(ctx, run_id=11, attempt=2)
    assert gh.calls[0].args == ["run", "view", "11", "--attempt", "2", "--json", github_workflows._RUN_FIELDS + ",jobs"]
    assert gh.calls[1].args == ["run", "view", "11", "--log", "--attempt", "2"]
    assert "run 11 attempt 2" in text


@pytest.mark.parametrize("run,attempt,fragment", [
    ({"databaseId": 12, "attempt": 1}, 0, "GitHub's answer for run 11 names run 12 attempt 1; the run was not read."),
    ({"databaseId": 11}, 0, "GitHub's answer for run 11 names run 11 attempt None; the run was not read."),
    ({"databaseId": 11, "attempt": 0}, 0, "names run 11 attempt 0; the run was not read."),
    ({"databaseId": 11, "attempt": 1}, 2, "GitHub's answer for run 11 attempt 2 names run 11 attempt 1; the run was not read."),
])
def test_run_log_never_invents_the_run_or_attempt_it_reads(fake, ctx, run, attempt, fragment):
    """A later re-run must not relabel bytes: the observed id and attempt are validated, never defaulted to 1."""
    gh = fake(run={"url": f"{BASE}/actions/runs/11", "status": "completed", "jobs": [], **run})
    text = github_workflows.get_run_log(ctx, run_id=11, attempt=attempt)
    assert gh.kinds() == ["run_json"] and text.startswith("⚠️ TOOL_ERROR: ") and fragment in text
    assert (_typed(ctx).status, _typed(ctx).code) == ("error", "TOOL_ERROR")


def test_run_log_cap_retains_the_first_bytes_and_says_the_log_is_longer(fake, ctx):
    gh = fake(log=b"line\n" * 1000)
    text = github_workflows.get_run_log(ctx, run_id=11, max_bytes=1234)
    assert gh.calls[1].max_bytes == 1234
    assert "captured 1234 bytes exactly; the 1234-byte cap ended the capture: the log is longer and this is its first 1234 bytes" in text
    assert _retained(ctx, text).read_bytes() == b"line\n" * 246 + b"line"


def test_run_log_empty_failed_steps_log_retains_nothing(fake, ctx):
    fake(log=b"")
    text = github_workflows.get_run_log(ctx, run_id=11, failed_only=True)
    assert "The log is empty: GitHub lists no failed step here, so --log-failed prints nothing. Nothing was retained." in text
    assert "Retained:" not in text


def test_run_log_tail_is_bounded_by_the_result_limit_and_clips_long_lines(fake, ctx, monkeypatch):
    monkeypatch.setattr(github_workflows, "tool_result_limit", lambda name: 2000)
    fake(log=(b"x" * 900 + b"\n") * 50)
    text = github_workflows.get_run_log(ctx, run_id=11, tail_lines=50)
    assert len(text) <= 2000
    shown = int(text.split("showing the last ", 1)[1].split(" ", 1)[0])
    assert 1 <= shown < 50 and f"Lines: 50; showing the last {shown} (each clipped to 400 chars)." in text
    assert text.endswith("x" * 399 + "…") and text.count("…") == shown


@pytest.mark.parametrize("kwargs,fragment", [
    ({"run_id": 0}, "run_id names the workflow run"),
    ({"run_id": "eleven"}, "whole numbers"),
    ({"run_id": 11, "failed_only": "yes"}, "failed_only is a boolean"),
    ({"run_id": 11, "max_bytes": 0}, "max_bytes is 1.."),
    ({"run_id": 11, "max_bytes": github_workflows.LOG_MAX_BYTES_CEILING + 1}, "max_bytes is 1.."),
    ({"run_id": 11, "tail_lines": 0}, "tail_lines is 1.."),
    ({"run_id": 11, "job_id": -1}, "job_id and attempt are 0"),
])
def test_run_log_argument_refusals_launch_nothing(fake, ctx, kwargs, fragment):
    gh = fake()
    text = github_workflows.get_run_log(ctx, **kwargs)
    assert fragment in text and gh.calls == []
    assert (_typed(ctx).code, _typed(ctx).meta["operation_outcome"]) == ("TOOL_ARG_ERROR", "completed_no_effect")


def test_run_log_malformed_json_and_transport_failures_are_reported_not_guessed(fake, ctx):
    gh = fake(failing={"run_json": github.GhResult(True, "not json", 0, None, "")})
    assert github_workflows.get_run_log(ctx, run_id=11).startswith("⚠️ TOOL_ERROR: failed to parse the workflow run JSON")
    forbidden = github.GhResult(False, "⚠️ GH_ERROR: gh: Resource not accessible (HTTP 403)", 1, 403, "exit")
    gh = fake(failing={"log": forbidden})
    assert github_workflows.get_run_log(ctx, run_id=11) == forbidden.text
    assert gh.kinds() == ["run_json", "log"]


# --- list_github_run_artifacts --------------------------------------------------------------------------------------

_DIST = {"id": 501, "name": "dist", "size_in_bytes": 2048, "expired": False, "created_at": "2026-10-20T10:00:00Z",
         "expires_at": "2027-01-18T10:00:00Z", "digest": "sha256:" + "0" * 64, "workflow_run": {"id": 11, "head_sha": SHA}}


def test_artifact_list_identifies_each_artifact_by_repository_and_id(fake, ctx):
    """Paired benefit over ``gh api …/artifacts``: the raw dump has names and ids but no repository; this call reads the
    run first, names the repository GitHub returned, and gives the exact id-addressed download call per artifact."""
    gh = fake(artifacts=[_DIST, {**_DIST, "id": 502, "name": "dist", "expired": True}])
    text = github_workflows.list_run_artifacts(ctx, run_id=11)
    assert gh.kinds() == ["run_json", "artifacts"]
    assert gh.calls[1].args == ["api", "repos/owner/selected/actions/runs/11/artifacts?per_page=100&page=1", "--hostname", "github.example"]
    assert gh.calls[1].repo is github._GENERIC_TRANSPORT, "the literal API path carries the repository GitHub named"
    assert text.startswith("GitHub Actions artifacts — owner/selected run 11 attempt 1: 2; page 1 of 1 (2 listed)\n")
    assert "Identity is repository + artifact id: the same name may exist in other runs and repositories." in text
    assert f"- id 501: dist — 2048 bytes; created 2026-10-20T10:00:00Z; expires 2027-01-18T10:00:00Z; head {SHA}; digest sha256:" in text
    assert "    download_github_artifact(artifact_id=501, max_bytes=2048)" in text
    assert "- id 502: dist — 2048 bytes, expired;" in text and "    expired: GitHub no longer serves it" in text


def test_artifact_list_of_the_same_name_in_two_repositories_gives_two_addresses(fake, ctx):
    first = fake(artifacts=[_DIST])
    one = github_workflows.list_run_artifacts(ctx, run_id=11)
    second = fake(run={"databaseId": 12, "url": f"{OTHER}/actions/runs/12", "status": "completed", "attempt": 1},
                  artifacts=[{**_DIST, "id": 777}])
    two = github_workflows.list_run_artifacts(ctx, run_id=12, repo="github.example/other/thing")
    assert first.calls[1].args[1] == "repos/owner/selected/actions/runs/11/artifacts?per_page=100&page=1"
    assert second.calls[1].args[1] == "repos/other/thing/actions/runs/12/artifacts?per_page=100&page=1"
    assert "download_github_artifact(artifact_id=501, max_bytes=2048)" in one
    assert "download_github_artifact(artifact_id=777, max_bytes=2048, repo='github.example/other/thing')" in two


def test_artifact_list_pages_explicitly_and_names_the_next_page(fake, ctx):
    """Paired benefit over a raw first page: every remaining record is reachable by an explicit page."""
    gh = fake(artifacts=[_DIST], total=150)
    assert "run 11 attempt 1: 150; page 1 of 2 (1 listed; page 2 holds the next)" in github_workflows.list_run_artifacts(ctx, run_id=11)
    text = github_workflows.list_run_artifacts(ctx, run_id=11, page=2)
    assert gh.calls[-1].args[1] == "repos/owner/selected/actions/runs/11/artifacts?per_page=100&page=2"
    assert "150; page 2 of 2 (1 listed)" in text and "page 3" not in text
    gh = fake(artifacts=[], total=1)
    assert github_workflows.list_run_artifacts(ctx, run_id=11, page=2).endswith("Page 2 lists no artifact (GitHub holds 1).")
    assert "page=2" in gh.calls[-1].args[1]
    fake(artifacts=[])
    assert github_workflows.list_run_artifacts(ctx, run_id=11).endswith("No artifact is registered for this run.")
    gh = fake(artifacts=[_DIST])
    assert "page starts at 1" in github_workflows.list_run_artifacts(ctx, run_id=11, page=-1) and gh.calls == []
    assert "whole number" in github_workflows.list_run_artifacts(ctx, run_id=11, page="two") and gh.calls == []
    assert "page 1 of 1" in github_workflows.list_run_artifacts(ctx, run_id=11, page=0), "0 reads as omitted: the first page"


def test_artifact_list_refusals(fake, ctx):
    gh = fake(failing={"artifacts": github.GhResult(True, "[]", 0, None, "")})
    assert github_workflows.list_run_artifacts(ctx, run_id=11).startswith("⚠️ TOOL_ERROR: failed to parse the artifacts JSON")
    assert github_workflows.list_run_artifacts(ctx, run_id=0) == ("⚠️ TOOL_ARG_ERROR: run_id is the positive workflow run number; "
                                                                  "page is a whole number.")
    assert gh.kinds() == ["run_json", "artifacts"]


# --- download_github_artifact ---------------------------------------------------------------------------------------

ARCHIVE = _zip({"report.xml": b"<testsuite/>", "logs/pytest.txt": b"1 failed\n"})


def test_artifact_download_retains_the_archive_unextracted_with_hash_and_listing(fake, ctx, tmp_path):
    """Paired benefit over ``gh run download -n dist``: the baseline selects by NAME and EXTRACTS into the working
    directory; this call selects by repository + id, bounds the download, keeps the archive as served with its sha256
    and lists its members without writing one of them anywhere."""
    gh = fake(artifact={**_DIST, "digest": "sha256:" + hashlib.sha256(ARCHIVE).hexdigest()}, archive=ARCHIVE)

    text = github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=1 << 20, repo="")

    assert gh.kinds() == ["repo", "artifact", "zip"]
    assert gh.calls[0].repo == "" and gh.calls[1].repo is gh.calls[2].repo is github._GENERIC_TRANSPORT
    assert gh.calls[2].args == ["api", "repos/owner/selected/actions/artifacts/501/zip", "--hostname", "github.example"]
    assert gh.calls[2].max_bytes == 1 << 20
    assert text.startswith(f"GitHub Actions artifact — owner/selected artifact 501 'dist' (run 11, head {SHA}); created ")
    assert f"Archive: {len(ARCHIVE)} bytes, sha256 {hashlib.sha256(ARCHIVE).hexdigest()}; GitHub's digest sha256:" in text and " matches these bytes" in text
    retained = task_artifact_dir_path(canonical_data_root(ctx), "task-fixture") / text.split("not extracted: artifact_store/", 1)[1].split(" ", 1)[0]
    assert retained.read_bytes() == ARCHIVE and retained.suffix == ".zip"
    assert "Members (2, 21 bytes uncompressed; names and sizes are read from the archive directory and are untrusted):" in text
    assert "  report.xml (12 bytes)\n  logs/pytest.txt (9 bytes)" in text
    extracted = [p for p in tmp_path.rglob("report.xml")] + [p for p in tmp_path.rglob("pytest.txt")]
    assert extracted == [], "no member was extracted anywhere"
    assert _typed(ctx).meta["operation_outcome"] == "completed_no_effect"


def test_artifact_download_digest_mismatch_is_stated_not_hidden(fake, ctx):
    fake(artifact={**_DIST, "digest": "sha256:" + "f" * 64}, archive=ARCHIVE)
    text = github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=4096)
    assert "GitHub's digest sha256:" + "f" * 64 + " differs from these bytes" in text


def test_artifact_download_refuses_before_downloading_when_too_large_or_expired(fake, ctx):
    gh = fake(artifact={**_DIST, "size_in_bytes": 5000})
    text = github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=4096)
    assert gh.kinds() == ["repo", "artifact"], "no zip request was sent"
    assert text == ("⚠️ TOOL_ARG_ERROR: artifact 501 'dist' of owner/selected is 5000 bytes, above max_bytes=4096; nothing was "
                    f"downloaded. Raise max_bytes deliberately (ceiling {github_workflows.ARTIFACT_MAX_BYTES_CEILING}).")
    assert _typed(ctx).meta["operation_outcome"] == "completed_no_effect"
    gh = fake(artifact={**_DIST, "expired": True})
    text = github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=4096)
    assert gh.kinds() == ["repo", "artifact"]
    assert text.startswith("⚠️ TOOL_ERROR: artifact 501 'dist' of owner/selected expired (2027-01-18T10:00:00Z); GitHub no longer serves it")


def test_artifact_download_over_the_cap_discards_the_partial_archive(fake, ctx):
    """GitHub stated a size under the cap but served more: the stream stopped at the cap and nothing is retained."""
    gh = fake(artifact={**_DIST, "size_in_bytes": 10}, archive=ARCHIVE)
    text = github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=100)
    assert gh.calls[2].max_bytes == 100
    assert text == ("⚠️ TOOL_ERROR: the download of artifact 501 'dist' of owner/selected exceeded max_bytes=100 (GitHub stated "
                    "10 bytes); the partial archive was discarded and nothing was retained.")
    store = task_artifact_dir_path(canonical_data_root(ctx), "task-fixture")
    assert not store.exists() or not list(store.rglob("*.zip"))


def test_artifact_download_non_zip_bytes_are_discarded(fake, ctx):
    fake(artifact=_DIST, archive=b'{"message":"Gone"}')
    text = github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=4096)
    assert text == "⚠️ TOOL_ERROR: the 18 bytes GitHub served for artifact 501 'dist' of owner/selected are not a zip archive; they were discarded."


def test_artifact_download_sends_the_explicit_repo_positionally_to_repo_view(ctx, monkeypatch):
    """Actual argv through the real transport: `gh repo view <repo>` (no --repo flag exists there), then the literal
    API path from the URL gh returned; the expired artifact stops the call before any download."""
    monkeypatch.setattr(github, "github_token_from_env_or_settings", lambda: "fixture-token")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["repo", "view"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"nameWithOwner": "other/thing", "url": OTHER}), stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({**_DIST, "expired": True}), stderr="")
    monkeypatch.setattr(subprocess, "run", run)

    text = github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=4096, repo="github.example/other/thing")

    assert calls[0] == ["gh", "repo", "view", "github.example/other/thing", "--json", "nameWithOwner,url"]
    assert calls[1] == ["gh", "api", "repos/other/thing/actions/artifacts/501", "--hostname", "github.example"]
    assert len(calls) == 2 and text.startswith("⚠️ TOOL_ERROR: artifact 501 'dist' of other/thing expired")


def test_artifact_download_targets_the_repository_the_cli_resolved(fake, ctx):
    gh = fake(repo_url=OTHER, artifact=_DIST, archive=ARCHIVE)
    text = github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=4096, repo="github.example/other/thing")
    assert gh.calls[0].args == ["repo", "view", "--json", "nameWithOwner,url"] and gh.calls[0].repo == "github.example/other/thing"
    assert gh.calls[1].args[1] == "repos/other/thing/actions/artifacts/501"
    assert text.startswith("GitHub Actions artifact — other/thing artifact 501 'dist'")


@pytest.mark.parametrize("kwargs,fragment", [
    ({"artifact_id": 501}, "max_bytes is required"),
    ({"artifact_id": 501, "max_bytes": 0}, "max_bytes is required"),
    ({"artifact_id": 501, "max_bytes": github_workflows.ARTIFACT_MAX_BYTES_CEILING + 1}, "max_bytes is required"),
    ({"artifact_id": 0, "max_bytes": 10}, "artifact_id is the id"),
    ({"artifact_id": "x", "max_bytes": 10}, "whole numbers"),
])
def test_artifact_download_argument_refusals_launch_nothing(fake, ctx, kwargs, fragment):
    gh = fake()
    assert fragment in github_workflows.download_artifact(ctx, **kwargs)
    assert gh.calls == [] and _typed(ctx).meta["operation_outcome"] == "completed_no_effect"


def test_artifact_download_malformed_or_mismatched_metadata_is_refused(fake, ctx):
    gh = fake(artifact={**_DIST, "id": 999})
    assert github_workflows.download_artifact(ctx, artifact_id=501, max_bytes=10).startswith("⚠️ TOOL_ERROR: the artifact answer is malformed or names another id")
    assert gh.kinds() == ["repo", "artifact"]


# --- registration -----------------------------------------------------------------------------------------------------

def test_readers_register_through_github_get_tools_with_repo_and_skip_policy():
    entries = {entry.name: entry for entry in github.get_tools()}
    for name in ("get_github_run_log", "list_github_run_artifacts", "download_github_artifact"):
        assert entries[name].safety_policy == "skip" and not entries[name].mutates_worktree
        assert entries[name].schema["parameters"]["properties"]["repo"]["type"] == "string"
    assert entries["download_github_artifact"].schema["parameters"]["required"] == ["artifact_id", "max_bytes"]
    assert not hasattr(github_workflows, "get_tools"), "registered by github.get_tools only"


def test_registered_reader_publishes_a_typed_completed_read(tmp_path, monkeypatch):
    from ouroboros.tools.registry import ToolRegistry

    monkeypatch.setattr(github, "github_token_from_env_or_settings", lambda: "fixture-token")
    gh = FakeGh()
    monkeypatch.setattr(github_workflows, "_gh_run", gh)
    ctx, _ = _context(tmp_path, "queued")
    registry = ToolRegistry(repo_dir=ctx.repo_dir, drive_root=ctx.drive_root)
    registry.set_context(ctx)
    result = registry.execute_result("get_github_run_log", {"run_id": 11, "repo": "github.example/owner/selected"})
    assert (result.status, result.code, result.meta["operation_outcome"]) == ("ok", "OK", "completed_no_effect")
    assert all(call.repo == "github.example/owner/selected" for call in gh.calls)
    refused = registry.execute_result("get_github_run_log", {"run_id": 0, "repo": "github.example/owner/selected"})
    assert (refused.status, refused.code, refused.meta["operation_outcome"]) == ("error", "TOOL_ARG_ERROR", "completed_no_effect")


def test_artifact_page_preview_keeps_every_omitted_record_addressable(fake, ctx, monkeypatch):
    monkeypatch.setattr(github_workflows, "tool_result_limit", lambda _name: 2000)
    rows = [{**_DIST, "id": 500 + i, "name": "long " * 40} for i in range(100)]
    fake(artifacts=rows)
    text = github_workflows.list_run_artifacts(ctx, run_id=11)
    assert len(text) <= 2000 and "omitted from this preview" in text
    import ast
    quoted = text.split("path=", 1)[1].split("); sha256", 1)[0]
    ref = ast.literal_eval(quoted)
    retained = task_artifact_dir_path(canonical_data_root(ctx), "task-fixture") / ref
    saved = json.loads(retained.read_text())
    assert saved["artifacts"] == rows and saved["total_count"] == 100


def test_artifact_page_unknown_total_never_means_complete(fake, ctx):
    fake(failing={"artifacts": _answer({"artifacts": [_DIST]})})
    text = github_workflows.list_run_artifacts(ctx, run_id=11)
    assert "no valid total_count; completeness is unknown" in text
    assert _typed(ctx).status == "error"


@pytest.mark.parametrize("size,expired,usable", [
    (github_workflows.ARTIFACT_MAX_BYTES_CEILING, False, True),
    (github_workflows.ARTIFACT_MAX_BYTES_CEILING + 1, False, False),
    (42, True, False),
])
def test_artifact_page_only_suggests_supported_downloads(fake, ctx, size, expired, usable):
    fake(artifacts=[{"id": 99, "name": "evidence", "size_in_bytes": size, "expired": expired}])
    text = github_workflows.list_run_artifacts(ctx, run_id=11)
    assert ("download_github_artifact(artifact_id=99" in text) is usable
    if expired:
        assert "expired: GitHub no longer serves it" in text
    elif not usable:
        assert "exceeds this tool's supported" in text


def test_old_job_requires_its_explicit_attempt(fake, ctx):
    gh = fake()
    first = {**gh.run, "attempt": 1}
    second = {**gh.run, "attempt": 2, "jobs": []}
    gh.run = second
    refused = github_workflows.get_run_log(ctx, run_id=11, job_id=55)
    assert "not a job of run 11 attempt 2" in refused
    assert gh.kinds() == ["run_json"]
    gh = fake(run=first)
    text = github_workflows.get_run_log(ctx, run_id=11, job_id=55, attempt=1)
    assert text.startswith("GitHub Actions log — owner/selected run 11 attempt 1, job 55")
    assert gh.calls[0].args[3:5] == ["--attempt", "1"]
    assert gh.calls[-1].args[-2:] == ["--attempt", "1"]
