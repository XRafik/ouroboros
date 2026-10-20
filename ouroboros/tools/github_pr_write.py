"""Pull-request writers: ``create_github_pr``, ``update_github_pr`` and ``set_github_pr_ready``.

Not a tool module: ``github.py`` registers these entries and owns the transport they call. Each call reads the
pull request, its head commit and (when it matters) its base commit first and refuses before any effect when they
differ from what the caller expected; then sends exactly ONE mutating ``gh`` command; then reads the pull request
back and states, field by field, what GitHub holds. Once a mutation was sent its effect is unknown until the
read-back shows it: a failed or lost answer is reported with gh's exit facts beside that read-back, never called a
refusal and never resent (a nonzero exit alone does not prove GitHub rejected the request, and a request GitHub is
still processing can land after the read). Nothing here pushes, forks or merges. ``skill_publish_github`` keeps its
token-only HTTP flow; the two share only the pure identity predicate in ``github_pr_identity``.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ouroboros.github_pr_identity import pull_request_fields_from_cli, same_pull_request
from ouroboros.tools.github import GhResult, _gh_run, _refuse, _send_facts
from ouroboros.tools.github_checks import _gh_json, _one_line, _whole
from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.tools.tool_result import ToolResult, _publish_tool_result

_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# A Git branch name this tool passes to gh: no whitespace or ref-forbidden characters, never flag-shaped.
_BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)(?!.*@\{)[^\s~^:?*\[\\\x00-\x1f\x7f]{1,255}(?<!/)(?<!\.lock)$")
_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_PR_URL_IN_TEXT_RE = re.compile(r"https://[^\s/]+/[^\s/]+/[^\s/]+/pull/(\d+)")
_REPO_URL_RE = re.compile(r"^https://([^/]+)/([^/]+)/([^/]+?)(?:/.*)?$")
_PR_FIELDS = "number,url,state,title,body,isDraft,headRefName,baseRefName,headRefOid,headRepositoryOwner"
_READ_TIMEOUT, _WRITE_TIMEOUT, _LIST_LIMIT = 30, 60, 50


@dataclass(frozen=True)
class _Repo:
    host: str
    owner: str
    name: str


def _sha(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if _FULL_SHA_RE.fullmatch(text) else ""


def _branch(value: object) -> str:
    text = str(value or "").strip() if isinstance(value, str) else ""
    return text if _BRANCH_RE.fullmatch(text) else ""


def _one_line_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value and "\r" not in value


def _ok(ctx: ToolContext, text: str, *, outcome: str = "completed") -> str:
    return _publish_tool_result(ctx, ToolResult(status="ok", code="OK", text=text, meta={"operation_outcome": outcome}))


def _failed(ctx: ToolContext, text: str, *, no_effect: bool = False) -> str:
    return _publish_tool_result(ctx, ToolResult(status="error", code="TOOL_ERROR", text=text,
                                                meta={"operation_outcome": "completed_no_effect"} if no_effect else {}))


def _precheck_failed(ctx: ToolContext, res: GhResult, what: str, nothing: str) -> str:
    """A read before the mutation failed, so nothing was sent; the transport's own refusals pass through."""
    if res.failure in ("target", "cli_missing"):
        return res.text
    return _failed(ctx, f"⚠️ PR_PRECHECK_FAILED: {what} could not be read ({res.text}); {nothing}.", no_effect=True)


def _hint(repo: str) -> str:
    """The ``repo=`` a recovery call must repeat so it reaches the same repository."""
    return f", repo={repo!r}" if repo else ""


def _where(repo: str) -> str:
    return repo or "the active Project repository"


def _malformed(what: str, res: GhResult) -> GhResult:
    return GhResult(False, f"⚠️ GH_ERROR: {what} is malformed: {res.text[:300]}", None, None, "malformed")


def _pr_record(data: object, number: int) -> Tuple[Optional[dict], str]:
    """The pull request fields this writer relies on, each checked for type, or why GitHub's answer lacks one."""
    if not isinstance(data, dict):
        return None, "not a JSON object"
    checks = {
        "number": lambda value: _whole(value) == number,
        "url": lambda value: isinstance(value, str) and bool(value),
        "state": lambda value: isinstance(value, str) and bool(value),
        "title": lambda value: isinstance(value, str),
        "isDraft": lambda value: isinstance(value, bool),
        "headRefName": lambda value: isinstance(value, str) and bool(value),
        "baseRefName": lambda value: isinstance(value, str) and bool(value),
        "headRefOid": lambda value: bool(_sha(value)),
    }
    for key, ok in checks.items():
        if key not in data or not ok(data[key]):
            return None, f"field {key!r} is {data.get(key)!r}"
    if "body" not in data:
        return None, "field 'body' is missing"
    if data["body"] is not None and not isinstance(data["body"], str):
        return None, "field 'body' is not text"
    owner = data.get("headRepositoryOwner")
    if not isinstance(owner, dict) or not isinstance(owner.get("login"), str) or not owner["login"]:
        return None, f"field 'headRepositoryOwner' is {owner!r}"
    return data, ""


def _resolve_repo(ctx: ToolContext, repo: str) -> Tuple[Optional[_Repo], str]:
    """The repository the CLI resolves for this call (the Project directory, or the explicit repo), from its URL."""
    res = _gh_run(["repo", "view", "--json", "nameWithOwner,url"], ctx, timeout=_READ_TIMEOUT, repo=repo)
    if not res.ok:
        return None, _precheck_failed(ctx, res, "the repository", "nothing was sent")
    info = _gh_json(res, dict)
    where = _REPO_URL_RE.match(str((info or {}).get("url") or ""))
    if where is None:
        return None, _failed(ctx, f"⚠️ PR_PRECHECK_FAILED: gh named no repository URL ({res.text[:300]}); nothing was sent.",
                             no_effect=True)
    return _Repo(*where.groups()), ""


def _ref_sha(ctx: ToolContext, repo: _Repo, owner: str, branch: str) -> Tuple[str, Optional[GhResult]]:
    """The commit a branch points at now, read from GitHub by the repository the run resolved; typed when malformed."""
    path = f"repos/{owner}/{repo.name}/git/ref/heads/{urllib.parse.quote(branch, safe='/')}"
    res = _gh_run(["api", path, "--hostname", repo.host], ctx, timeout=_READ_TIMEOUT)
    if not res.ok:
        return "", res
    data = _gh_json(res, dict)
    target = data.get("object") if isinstance(data, dict) else None
    sha = _sha(target.get("sha")) if isinstance(target, dict) else ""
    if not sha:
        return "", _malformed(f"the ref answer for {owner}/{repo.name} {branch}", res)
    return sha, None


def _view(ctx: ToolContext, number: int, repo: str) -> Tuple[Optional[dict], Optional[GhResult]]:
    """The pull request as GitHub answers it, with every relied-on field validated; typed when malformed."""
    res = _gh_run(["pr", "view", str(number), "--json", _PR_FIELDS], ctx, timeout=_READ_TIMEOUT, repo=repo)
    if not res.ok:
        return None, res
    pr, why = _pr_record(_gh_json(res, dict), number)
    if pr is None:
        return None, _malformed(f"the pull request answer ({why})", res)
    return pr, None


def _open_prs(ctx: ToolContext, repo: str, branch: str, base: str) -> Tuple[Optional[list], Optional[GhResult]]:
    """The open pull requests GitHub lists from a head branch name into a base; owners are told apart afterwards."""
    res = _gh_run(["pr", "list", "--state", "open", f"--head={branch}", f"--base={base}", "--limit", str(_LIST_LIMIT),
                   "--json", _PR_FIELDS], ctx, timeout=_READ_TIMEOUT, repo=repo)
    if not res.ok:
        return None, res
    rows = _gh_json(res, list)
    if rows is None:
        return None, _malformed("the pull request list answer", res)
    return [row for row in rows if isinstance(row, dict)], None


def _matching(rows: list, *, head_owner: str, head_branch: str, base: str, head_sha: Optional[str]) -> list:
    return [row for row in rows if same_pull_request(pull_request_fields_from_cli(row), head_owner=head_owner,
                                                     head_branch=head_branch, base_branch=base, head_sha=head_sha)]


def _pr_line(pr: dict) -> str:
    owner = pr.get("headRepositoryOwner") if isinstance(pr.get("headRepositoryOwner"), dict) else {}
    return (f"PR #{pr.get('number')} {pr.get('url') or ''}: {str(pr.get('state') or 'state unknown').lower()}, "
            f"{owner.get('login') or '?'}:{pr.get('headRefName') or '?'} → {pr.get('baseRefName') or '?'}, "
            f"head {pr.get('headRefOid') or 'unknown'}, draft={bool(pr.get('isDraft'))}, title {_one_line(pr.get('title'), 100)!r}")


def _normalized(text: object) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()


def _reconcile(pr: dict, *, title: Optional[str] = None, body: Optional[str] = None, base: Optional[str] = None,
               draft: Optional[bool] = None, head_owner: Optional[str] = None, head_branch: Optional[str] = None,
               head_sha: Optional[str] = None) -> Tuple[List[str], List[str], List[str]]:
    """What the read-back confirms, where it differs on a requested field, and notes on the head commit.

    The head commit is what the caller read, not what the call changes: its movement is reported, never counted
    as a differing field."""
    confirmed: List[str] = []
    differs: List[str] = []
    notes: List[str] = []
    if title is not None:
        held = pr.get("title")
        (confirmed if held == title else differs).append(
            "title confirmed" if held == title else f"title is {_one_line(held, 120)!r}, you sent {_one_line(title, 120)!r}")
    if body is not None:
        held = "" if pr.get("body") is None else str(pr.get("body"))
        if held == body:
            confirmed.append(f"body confirmed ({len(body)} chars)")
        elif _normalized(held) == _normalized(body):
            confirmed.append(f"body confirmed after line-ending and trailing-whitespace normalization ({len(held)} chars held)")
        else:
            differs.append(f"body differs ({len(held)} chars held, {len(body)} sent)")
    if base is not None:
        held = pr.get("baseRefName")
        (confirmed if held == base else differs).append(
            f"base {base} confirmed" if held == base else f"base is {held!r}, you asked for {base!r}")
    if draft is not None:
        held = bool(pr.get("isDraft"))
        (confirmed if held == draft else differs).append(
            f"draft={held} confirmed" if held == draft else f"draft is {held}, you asked for {draft}")
    if head_branch is not None:
        owner = pr.get("headRepositoryOwner") if isinstance(pr.get("headRepositoryOwner"), dict) else {}
        held = f"{owner.get('login') or '?'}:{pr.get('headRefName') or '?'}"
        wanted = f"{head_owner}:{head_branch}"
        same = pr.get("headRefName") == head_branch and str(owner.get("login") or "").casefold() == str(head_owner or "").casefold()
        (confirmed if same else differs).append(f"head {wanted} confirmed" if same else f"head is {held}, you asked for {wanted}")
    if head_sha is not None:
        held = _sha(pr.get("headRefOid"))
        (confirmed if held == head_sha else notes).append(
            f"head at {head_sha} confirmed" if held == head_sha else f"head moved to {held} since you read it (you expected {head_sha})")
    return confirmed, differs, notes


def _readback_lines(confirmed: List[str], differs: List[str], notes: List[str]) -> List[str]:
    lines = ["Read-back: " + "; ".join(confirmed)] if confirmed else []
    if differs:
        lines.append("⚠️ Read-back differs: " + "; ".join(differs) + ". Read the pull request again before relying on it.")
    if notes:
        lines.append("Note: " + "; ".join(notes))
    return lines


def _settled(ctx: ToolContext, headline: str, pr: dict, **expected: object) -> str:
    """A mutation gh accepted, judged by its read-back: completed only when every requested field is held."""
    confirmed, differs, notes = _reconcile(pr, **expected)
    return _ok(ctx, "\n".join([headline] + _readback_lines(confirmed, differs, notes)),
               outcome="unknown" if differs else "completed")


def create_pr(ctx: ToolContext, title: object = "", head: object = "", base: object = "", expected_head_sha: object = "",
              expected_base_sha: object = "", body: object = "", draft: object = False, repo: str = "") -> str:
    """Open one pull request from an existing head branch, after the head and base read as the caller expected."""
    if not _one_line_text(title):
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: title is one non-empty line.", no_effect=True)
    head_arg = head.strip() if isinstance(head, str) else ""
    owner_part, _sep, branch_part = head_arg.rpartition(":")
    head_branch, base_arg = _branch(branch_part), _branch(base)
    if not head_branch or (owner_part and not _LOGIN_RE.fullmatch(owner_part)):
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: head is an existing branch name, or OWNER:BRANCH for a head held by another "
                            "account; this tool pushes and forks nothing.", no_effect=True)
    if not base_arg:
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: base is the branch name the change should merge into.", no_effect=True)
    head_sha, base_sha = _sha(expected_head_sha), _sha(expected_base_sha)
    if not head_sha or not base_sha:
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: expected_head_sha and expected_base_sha are the full 40-hex commits you read "
                            "for the head and base branches; the call refuses before any effect when GitHub holds others.",
                       no_effect=True)
    if head_sha == base_sha:
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: expected_head_sha equals expected_base_sha; there is nothing to request.",
                       no_effect=True)
    if not isinstance(body, str):
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: body is a string; an omitted body is an empty body.", no_effect=True)
    if not isinstance(draft, bool):
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: draft is a boolean.", no_effect=True)

    repo_id, error = _resolve_repo(ctx, repo)
    if repo_id is None:
        return error
    head_owner = owner_part or repo_id.owner
    head_label = f"{head_owner}:{head_branch}"
    if head_owner.casefold() == repo_id.owner.casefold() and head_branch == base_arg:
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: head and base are the same branch.", no_effect=True)
    current, res = _ref_sha(ctx, repo_id, head_owner, head_branch)
    if res is not None:
        return _precheck_failed(ctx, res, f"head {head_label}", "nothing was created")
    if current != head_sha:
        return _failed(ctx, f"⚠️ PR_PRECHECK_FAILED: head {head_label} is at {current}, you expected {head_sha}; nothing was "
                            "created. Re-read the head and decide again.", no_effect=True)
    current, res = _ref_sha(ctx, repo_id, repo_id.owner, base_arg)
    if res is not None:
        return _precheck_failed(ctx, res, f"base {base_arg}", "nothing was created")
    if current != base_sha:
        return _failed(ctx, f"⚠️ PR_PRECHECK_FAILED: base {base_arg} is at {current}, you expected {base_sha}; nothing was "
                            "created. Re-read the base and decide again.", no_effect=True)
    rows, res = _open_prs(ctx, repo, head_branch, base_arg)
    if res is not None:
        return _precheck_failed(ctx, res, f"the open pull requests from {head_branch} into {base_arg}", "nothing was created")
    existing = _matching(rows, head_owner=head_owner, head_branch=head_branch, base=base_arg, head_sha=None)
    if existing:
        return _failed(ctx, f"⚠️ PR_EXISTS: {_pr_line(existing[0])} is already open for {head_label} into {base_arg} in "
                            f"{_where(repo)}; nothing was created. Change it with update_github_pr(number="
                            f"{existing[0].get('number')}{_hint(repo)}).", no_effect=True)

    # The one mutation. Values ride as `--flag=value` or stdin, never as a following argument.
    args = ["pr", "create", f"--title={title}", f"--head={head_arg}", f"--base={base_arg}", "--body-file=-"] + (
        ["--draft"] if draft else [])
    sent = _gh_run(args, ctx, timeout=_WRITE_TIMEOUT, input_data=body, repo=repo)
    expected = dict(title=title, body=body, base=base_arg, draft=draft, head_owner=head_owner, head_branch=head_branch,
                    head_sha=head_sha)
    if sent.ok:
        match = _PR_URL_IN_TEXT_RE.search(sent.text)
        number = int(match.group(1)) if match else 0
        if not number:
            rows, res = _open_prs(ctx, repo, head_branch, base_arg)
            found = _matching(rows or [], head_owner=head_owner, head_branch=head_branch, base=base_arg, head_sha=head_sha)
            if res is not None or len(found) != 1:
                return _failed(ctx, f"⚠️ PR_CREATE_UNKNOWN: gh reported success but named no pull request ({sent.text[:200]!r}), "
                                    "and the read-back " + (f"failed ({res.text})" if res is not None else
                                                            f"found {len(found)} open pull requests for {head_label} into {base_arg}")
                               + f". One request was sent and not retried. Inspect {_where(repo)} (list_github_prs{_hint(repo)}) "
                                 "before creating again.")
            number = _whole(found[0].get("number")) or 0
        if number <= 0:
            return _failed(ctx, "⚠️ PR_CREATE_UNKNOWN: gh reported success but read-back named no valid PR number. "
                           "One request was sent and not retried; inspect the repository before creating again.")
        pr, res = _view(ctx, number, repo)
        if pr is None:
            return _ok(ctx, f"✅ PR #{number} created: {match.group(0) if match else 'URL not named by gh'}\n⚠️ Read-back failed "
                            f"({res.text}): the pull request's fields are unconfirmed; read it with "
                            f"get_github_pr(number={number}{_hint(repo)}).", outcome="unknown")
        return _settled(ctx, f"✅ PR #{number} created: {pr['url']}", pr, **expected)

    # The send failed or its answer was lost: exactly one request went out and its effect is unknown; read.
    prefix = (f"⚠️ PR_CREATE_UNKNOWN: the create request for {head_label} into {base_arg} in {_where(repo)} "
              f"{_send_facts(sent)}. One request was sent and not retried; its effect is unknown until GitHub shows it.")
    rows, res = _open_prs(ctx, repo, head_branch, base_arg)
    if res is not None:
        return _failed(ctx, prefix + f" Read-back failed too ({res.text}); list the open pull requests "
                                     f"(list_github_prs{_hint(repo)}) before creating again.")
    found = _matching(rows, head_owner=head_owner, head_branch=head_branch, base=base_arg, head_sha=None)
    if not found:
        return _failed(ctx, prefix + f" Read-back: GitHub listed no open pull request from {head_label} into {base_arg} at that "
                                     "moment; a request it is still processing would appear later, so read again "
                                     f"(list_github_prs{_hint(repo)}) before creating.")
    exact = _matching(found, head_owner=head_owner, head_branch=head_branch, base=base_arg, head_sha=head_sha)
    return _failed(ctx, prefix + f" Read-back: {_pr_line((exact or found)[0])} is open for this head and base"
                   + (" at the expected commit" if exact else " at another commit")
                   + " — this call's effect or an earlier one; do not create again. Compare its fields and use "
                     f"update_github_pr(number={(exact or found)[0].get('number')}{_hint(repo)}) if they differ.")


def update_pr(ctx: ToolContext, number: object = 0, expected_head_sha: object = "", title: object = None,
              body: object = None, base: object = None, expected_base_sha: object = "", repo: str = "") -> str:
    """Change the title, body and/or base of one open pull request in one edit, after it reads as expected."""
    number = _whole(number)
    if number is None or number <= 0:
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: number is the positive pull request number.", no_effect=True)
    head_sha = _sha(expected_head_sha)
    if not head_sha:
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: expected_head_sha is the full 40-hex head commit you read for this pull "
                            "request; the call refuses before any effect when the head moved.", no_effect=True)
    if title is None and body is None and base is None:
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: nothing to change: pass title, body (\"\" clears it; omitted leaves it) "
                            "and/or base.", no_effect=True)
    if title is not None and not _one_line_text(title):
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: title is one non-empty line.", no_effect=True)
    if body is not None and not isinstance(body, str):
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: body is a string: \"\" clears it, omit it to leave it unchanged.", no_effect=True)
    base_arg, base_sha = None, ""
    if base is not None:
        base_arg, base_sha = _branch(base), _sha(expected_base_sha)
        if not base_arg:
            return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: base is a branch name.", no_effect=True)
        if not base_sha:
            return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: expected_base_sha is required with base: the full 40-hex commit you read "
                                "for the new base branch.", no_effect=True)

    pr, res = _view(ctx, number, repo)
    if pr is None:
        return _precheck_failed(ctx, res, f"pull request #{number}", "nothing was changed")
    state = str(pr.get("state") or "")
    if state != "OPEN":
        return _failed(ctx, f"⚠️ PR_PRECHECK_FAILED: {_pr_line(pr)} is {state.lower() or 'in an unknown state'}, not open; "
                            "nothing was changed.", no_effect=True)
    current = _sha(pr["headRefOid"])
    if current != head_sha:
        return _failed(ctx, f"⚠️ PR_PRECHECK_FAILED: the head of PR #{number} is at {current}, you expected {head_sha}; nothing "
                            "was changed. Re-read the pull request and decide again.", no_effect=True)
    requested_base = base_arg
    if base_arg is not None and pr.get("baseRefName") == base_arg:
        # Supplying the current base does not cancel requested title/body edits.
        base_arg = None
    if (base_arg is None and (title is None or title == pr["title"])
            and (body is None or body == (pr["body"] or ""))):
        return _ok(ctx, f"PR #{number} already holds the requested values; nothing was changed. {pr['url']}",
                   outcome="completed_no_effect")
    if base_arg is not None:
        repo_id, error = _resolve_repo(ctx, repo)
        if repo_id is None:
            return error
        current, res = _ref_sha(ctx, repo_id, repo_id.owner, base_arg)
        if res is not None:
            return _precheck_failed(ctx, res, f"base {base_arg}", "nothing was changed")
        if current != base_sha:
            return _failed(ctx, f"⚠️ PR_PRECHECK_FAILED: base {base_arg} is at {current}, you expected {base_sha}; nothing was "
                                "changed.", no_effect=True)

    # The one mutation: gh pr edit updates title, body and base in one request.
    args = ["pr", "edit", str(number)] + ([f"--title={title}"] if title is not None else []) + (
        ["--body-file=-"] if body is not None else []) + ([f"--base={base_arg}"] if base_arg is not None else [])
    sent = _gh_run(args, ctx, timeout=_WRITE_TIMEOUT, input_data=body if body is not None else None, repo=repo)
    requested = dict(title=title, body=body, base=requested_base)
    after, res = _view(ctx, number, repo)
    if sent.ok:
        if after is None:
            return _ok(ctx, f"✅ gh accepted the edit of PR #{number}.\n⚠️ Read-back failed ({res.text}): the fields are "
                            f"unconfirmed; read them with get_github_pr(number={number}{_hint(repo)}).", outcome="unknown")
        confirmed, differs, notes = _reconcile(after, **requested, head_sha=head_sha)
        headline = (f"✅ PR #{number} updated: {after['url']}" if not differs else
                    f"⚠️ gh accepted the edit of PR #{number} ({after['url']}), but the read-back does not hold every requested value.")
        return _ok(ctx, "\n".join([headline] + _readback_lines(confirmed, differs, notes)),
                   outcome="unknown" if differs else "completed")

    prefix = (f"⚠️ PR_UPDATE_UNKNOWN: the edit request for PR #{number} in {_where(repo)} {_send_facts(sent)}. One request "
              "was sent and not retried; its effect is unknown until GitHub shows it.")
    if after is None:
        return _failed(ctx, prefix + f" Read-back failed too ({res.text}); read the pull request "
                                     f"(get_github_pr(number={number}{_hint(repo)})) before editing again.")
    confirmed, differs, _notes = _reconcile(after, **requested)
    if not confirmed:
        return _failed(ctx, prefix + " Read-back: none of the requested values was held at that moment (" + "; ".join(differs)
                       + "); a request GitHub is still processing could still land, so read again before resending.")
    if not differs:
        return _failed(ctx, prefix + " Read-back: GitHub holds every requested value (" + "; ".join(confirmed) + "); do not resend.")
    return _failed(ctx, prefix + " Read-back at that moment: held: " + "; ".join(confirmed) + "; not held: " + "; ".join(differs)
                   + ". Read again before resending only the fields not held.")


def set_pr_ready(ctx: ToolContext, number: object = 0, ready: object = True, expected_head_sha: object = "",
                 repo: str = "") -> str:
    """Mark one open pull request ready for review (or back to draft), after it reads as expected."""
    number = _whole(number)
    if number is None or number <= 0:
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: number is the positive pull request number.", no_effect=True)
    if not isinstance(ready, bool):
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: ready is a boolean: true marks the draft ready for review, false converts "
                            "the pull request back to a draft.", no_effect=True)
    head_sha = _sha(expected_head_sha)
    if not head_sha:
        return _refuse(ctx, "⚠️ TOOL_ARG_ERROR: expected_head_sha is the full 40-hex head commit you read for this pull "
                            "request; the call refuses before any effect when the head moved.", no_effect=True)
    want = "ready for review" if ready else "a draft"

    pr, res = _view(ctx, number, repo)
    if pr is None:
        return _precheck_failed(ctx, res, f"pull request #{number}", "nothing was changed")
    state = str(pr.get("state") or "")
    if state != "OPEN":
        return _failed(ctx, f"⚠️ PR_PRECHECK_FAILED: {_pr_line(pr)} is {state.lower() or 'in an unknown state'}, not open; "
                            "nothing was changed.", no_effect=True)
    current = _sha(pr["headRefOid"])
    if current != head_sha:
        return _failed(ctx, f"⚠️ PR_PRECHECK_FAILED: the head of PR #{number} is at {current}, you expected {head_sha}; nothing "
                            "was changed. Re-read the pull request and decide again.", no_effect=True)
    if pr["isDraft"] == (not ready):
        return _ok(ctx, f"PR #{number} is already {want}; nothing was changed. {pr['url']}", outcome="completed_no_effect")

    sent = _gh_run(["pr", "ready", str(number)] + ([] if ready else ["--undo"]), ctx, timeout=_WRITE_TIMEOUT, repo=repo)
    after, res = _view(ctx, number, repo)
    if sent.ok:
        if after is None:
            return _ok(ctx, f"✅ gh accepted marking PR #{number} {want}.\n⚠️ Read-back failed ({res.text}): the state is "
                            f"unconfirmed; read it with get_github_pr(number={number}{_hint(repo)}).", outcome="unknown")
        confirmed, differs, notes = _reconcile(after, draft=not ready, head_sha=head_sha)
        headline = (f"✅ PR #{number} is now {want}: {after['url']}" if not differs else
                    f"⚠️ gh accepted marking PR #{number} {want} ({after['url']}), but the read-back does not show that state.")
        return _ok(ctx, "\n".join([headline] + _readback_lines(confirmed, differs, notes)),
                   outcome="unknown" if differs else "completed")

    prefix = (f"⚠️ PR_READY_UNKNOWN: the request to mark PR #{number} in {_where(repo)} {want} {_send_facts(sent)}. One "
              "request was sent and not retried; its effect is unknown until GitHub shows it.")
    if after is None:
        return _failed(ctx, prefix + f" Read-back failed too ({res.text}); read the pull request "
                                     f"(get_github_pr(number={number}{_hint(repo)})) before acting.")
    held = after["isDraft"]
    if held == (not ready):
        return _failed(ctx, prefix + f" Read-back: GitHub reports draft={held}, the requested state; do not resend.")
    return _failed(ctx, prefix + f" Read-back: GitHub still reported draft={held} at that moment; a request it is still "
                                 "processing could still land, so read again before resending.")


def tool_entries() -> List[ToolEntry]:
    """Registered by ``github.get_tools`` (which adds the ``repo`` parameter); never a ``get_tools`` of this module."""
    sha_words = "the full 40-hex commit you read"
    precheck = ("Expected SHAs are prechecks read just before the send, not a server-side compare-and-swap: a ref that "
                "moves between the check and the send is not caught; the read-back reports what GitHub holds.")
    return [
        ToolEntry("create_github_pr", {
            "name": "create_github_pr",
            "description": (
                "Open one GitHub pull request from a branch that already exists on GitHub. Before any effect it reads "
                "the head and base branches and the open pull requests, and refuses when the head or base is not at the "
                "commit you expected or a pull request for this head and base is already open. Then it sends exactly "
                "one create request and reads the pull request back, confirming title, body, base, head and draft state "
                "field by field. A failed or lost answer is reported with what GitHub holds, never resent. Pushes, "
                "forks and merges nothing: push first with the git tools, merge with pr_merge. " + precheck
            ),
            "parameters": {"type": "object", "properties": {
                "title": {"type": "string", "description": "One-line title."},
                "head": {"type": "string", "description": "Existing head branch name, or OWNER:BRANCH for a head held by another account; "
                                                          "that precheck reads OWNER/<same repository name>, so a fork under a different name "
                                                          "is refused as not found."},
                "base": {"type": "string", "description": "Base branch name to merge into."},
                "expected_head_sha": {"type": "string", "description": f"Head branch commit, {sha_words} (e.g. after pushing and reading vcs_read action=rev_parse)."},
                "expected_base_sha": {"type": "string", "description": f"Base branch commit, {sha_words}."},
                "body": {"type": "string", "default": "", "description": "Markdown body; omitted means empty."},
                "draft": {"type": "boolean", "default": False, "description": "Open as a draft."},
            }, "required": ["title", "head", "base", "expected_head_sha", "expected_base_sha"]},
        }, create_pr, safety_policy="check"),

        ToolEntry("update_github_pr", {
            "name": "update_github_pr",
            "description": (
                "Change the title, body and/or base branch of one open GitHub pull request in one edit request. Before "
                "any effect it reads the pull request and refuses when it is not open or its head is not at the commit "
                "you expected (and, for a new base, when that branch is not at expected_base_sha). An omitted body is "
                "left as it is; an empty body clears it. Reads the pull request back and reports each field as "
                "confirmed or differing; a failed or lost answer is reported with what GitHub holds, never resent. " + precheck
            ),
            "parameters": {"type": "object", "properties": {
                "number": {"type": "integer", "description": "Pull request number."},
                "expected_head_sha": {"type": "string", "description": f"The pull request's head commit, {sha_words}."},
                "title": {"type": "string", "description": "New one-line title; omit to leave it."},
                "body": {"type": "string", "description": "New Markdown body; \"\" clears it; omit to leave it."},
                "base": {"type": "string", "description": "New base branch; omit to leave it. Requires expected_base_sha."},
                "expected_base_sha": {"type": "string", "default": "", "description": f"With base: the new base branch's commit, {sha_words}."},
            }, "required": ["number", "expected_head_sha"]},
        }, update_pr, safety_policy="check"),

        ToolEntry("set_github_pr_ready", {
            "name": "set_github_pr_ready",
            "description": (
                "Mark one open GitHub pull request ready for review (ready=true) or convert it back to a draft "
                "(ready=false), in one request, after reading that it is open and its head is at the commit you "
                "expected. A pull request already in the requested state is reported as unchanged. Reads the state "
                "back; a failed or lost answer is reported with what GitHub holds, never resent. " + precheck
            ),
            "parameters": {"type": "object", "properties": {
                "number": {"type": "integer", "description": "Pull request number."},
                "ready": {"type": "boolean", "default": True, "description": "true: ready for review; false: back to draft."},
                "expected_head_sha": {"type": "string", "description": f"The pull request's head commit, {sha_words}."},
            }, "required": ["number", "expected_head_sha"]},
        }, set_pr_ready, safety_policy="check"),
    ]
