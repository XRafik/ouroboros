"""Read local Git history and identity from a dispatch-selected repository.

``repository`` selects a worktree before policy guards run; ``path`` is only a
literal filter inside it. These reads never fetch, stage, or serialize an index.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
from typing import Optional

from ouroboros.protected_artifacts import block_reason_for_path, protected_artifact_paths
from ouroboros.tool_access import ResolvedResourceBinding
from ouroboros.tools.git_plumbing import _publish_git_error, _sanitize_git_error
from ouroboros.tools.tool_result import ToolResult, _publish_tool_result

READ_DESCRIPTION = (
    "Inspect local Git history, historical file content, refs, merge ancestry, or "
    "repository identity without changing the repository or contacting a remote. "
    "Select a worktree with root and optional repository; path only filters files "
    "inside that worktree. Actions: log lists commits; show displays one commit's "
    "patch; file reads a file at a commit; blame attributes historical lines; refs "
    "lists local refs; rev_parse resolves an object; merge_base finds common ancestry; "
    "identity reports the current HEAD, branch, worktree, Git directories, and dirty "
    "state as sequential observations, not proof of an exact staged subject. "
    "ref selects a local revision (or a refs/ prefix for refs); merge_base uses "
    "base and head. max_count bounds log entries and max_chars truncates rendered output."
)

_CONTENT_ACTIONS = frozenset({"show", "file", "blame"})
_ACTIONS = frozenset({"log", "show", "file", "blame", "refs", "rev_parse", "merge_base", "identity"})


def _capture_read_git(repo: pathlib.Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Capture one local Git read with operator Git state and helpers disabled."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({
        "LC_ALL": "C", "LANG": "C", "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
    })
    cmd = [
        "git", "--no-pager", "--no-optional-locks",
        "-c", "core.fsmonitor=false", "-c", "core.pager=cat",
        "-c", f"core.hooksPath={os.devnull}",
        "-c", "log.showSignature=false",
    ]
    if args and args[0] in {"status", "diff"}:
        # Worktree comparison can run repository clean/process filters. Read
        # their configured driver names with Git's config parser, then blank
        # only those helper slots for this invocation. Config inspection does
        # not execute a filter and does not alter the repository.
        configured = subprocess.run(
            [*cmd, "config", "--null", "--name-only", "--get-regexp",
             r"^filter\..*\.(clean|smudge|process|required)$"],
            cwd=repo, capture_output=True, env=env, timeout=30,
        )
        if configured.returncode not in (0, 1):
            raise _git_failure(configured)
        drivers = {
            key.decode("utf-8", "surrogateescape").rsplit(".", 1)[0]
            for key in configured.stdout.split(b"\0") if key
        }
        for driver in sorted(drivers):
            for slot in ("clean", "smudge", "process"):
                cmd.extend(["-c", f"{driver}.{slot}="])
            cmd.extend(["-c", f"{driver}.required=false"])
    return subprocess.run([*cmd, *args], cwd=repo, capture_output=True, env=env, timeout=30)


def _git_failure(completed: subprocess.CompletedProcess[bytes]) -> RuntimeError:
    detail = completed.stderr.decode("utf-8", "replace").strip() or f"exit {completed.returncode}"
    return RuntimeError(detail)


def _run_read_git(repo: pathlib.Path, args: list[str], *, preserve_output: bool = False) -> str:
    completed = _capture_read_git(repo, args)
    if completed.returncode:
        raise _git_failure(completed)
    text = completed.stdout.decode("utf-8", "backslashreplace")
    return text if preserve_output else text.rstrip()


def _object(repo: pathlib.Path, ref: str, kind: str) -> str:
    if not ref.strip() or "\x00" in ref or "\n" in ref:
        raise ValueError("ref must be a nonempty local Git revision")
    oid = _run_read_git(repo, ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{{kind}}}"])
    if len(oid) not in (40, 64) or any(c not in "0123456789abcdef" for c in oid):
        raise ValueError("Git did not resolve one exact object")
    return oid


def _literal_path(binding: ResolvedResourceBinding, path: str) -> str:
    if not path:
        return ""
    from ouroboros.utils import normalized_path_text

    # The binding proves current physical confinement; Git needs the requested
    # tree entry, not a symlink's current target (which may have different bytes).
    if not binding.target_path.is_relative_to(binding.repository_path or binding.base_path):
        raise ValueError("path escapes the selected repository")
    relative = pathlib.PurePosixPath(normalized_path_text(path)).as_posix()
    if relative.startswith("/") or ".." in pathlib.PurePosixPath(relative).parts:
        raise ValueError("path must be repository-relative")
    if relative in {"", "."}:
        raise ValueError("path must name a file inside the selected repository")
    return relative


def _protected_content_reason(ctx, binding: ResolvedResourceBinding, path: str, action: str) -> str:
    operation = "read_bytes" if action == "file" else "static_introspection"
    if path:
        if reason := block_reason_for_path(ctx, binding.target_path, operation, binding):
            return reason
    # Historical entries may be gone from the worktree. Compare policy ancestry
    # as paths, without relying on Path.is_dir() for a removed protected folder.
    target = binding.target_path if path else (binding.repository_path or binding.base_path)
    for protected in protected_artifact_paths(ctx, binding):
        try:
            protected.relative_to(target)
        except ValueError:
            try:
                target.relative_to(protected)
            except ValueError:
                continue
        if reason := block_reason_for_path(ctx, protected, operation, binding):
            return reason
    return ""


def _identity(repo: pathlib.Path) -> str:
    toplevel = _run_read_git(repo, ["rev-parse", "--show-toplevel"])
    if pathlib.Path(toplevel).resolve(strict=False) != repo.resolve(strict=False):
        raise ValueError("repository must name the Git worktree root")
    git_dir = _run_read_git(repo, ["rev-parse", "--absolute-git-dir"])
    common_dir = _run_read_git(repo, ["rev-parse", "--git-common-dir"])
    common_path = pathlib.Path(common_dir)
    if not common_path.is_absolute():
        common_path = repo / common_path
    common_path = common_path.resolve(strict=False)
    branch_probe = _capture_read_git(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    if branch_probe.returncode == 0:
        branch = branch_probe.stdout.decode("utf-8", "replace").strip()
    elif branch_probe.returncode == 1 and not branch_probe.stdout and not branch_probe.stderr:
        branch = None  # Detached HEAD is the documented quiet exit.
    else:
        raise _git_failure(branch_probe)
    head_probe = _capture_read_git(repo, ["rev-parse", "--verify", "HEAD^{commit}"])
    if head_probe.returncode == 0:
        head = head_probe.stdout.decode("ascii", "replace").strip()
    else:
        # An unborn branch has a valid symbolic HEAD but no branch ref. A
        # broken existing ref, detached failure, or any other Git failure must
        # remain an error rather than masquerading as an empty repository.
        if not branch or head_probe.stdout:
            raise _git_failure(head_probe)
        full_ref = _run_read_git(repo, ["symbolic-ref", "HEAD"])
        missing = _capture_read_git(repo, ["show-ref", "--verify", "--quiet", full_ref])
        if (missing.returncode != 1 or missing.stdout or missing.stderr
                or (common_path / full_ref).exists()):
            raise _git_failure(head_probe)
        head = None
    return json.dumps({
        "worktree": toplevel,
        "git_dir": str(pathlib.Path(git_dir).resolve(strict=False)),
        "common_dir": str(common_path),
        "head": head,
        "branch": branch,
        "dirty": bool(_run_read_git(repo, ["status", "--porcelain=v1", "--untracked-files=all"])),
    }, ensure_ascii=False, sort_keys=True)


def _vcs_read(
    ctx,
    action: str,
    root: str = "active_workspace",
    repository: str = "",
    path: str = "",
    ref: str = "",
    base: str = "",
    head: str = "",
    max_count: int = 20,
    max_chars: int = 0,
    _resolved_binding: Optional[ResolvedResourceBinding] = None,
) -> str:
    """Read Git objects using only the prepared repository and path binding."""
    if (action not in _ACTIONS or not isinstance(max_count, int)
            or not isinstance(max_chars, int) or not 1 <= max_count <= 200 or max_chars < 0
            or (path and action not in {"log", "show", "file", "blame"})
            or ((base or head) and action != "merge_base")
            or (ref and action in {"merge_base", "identity"})):
        return _publish_tool_result(ctx, ToolResult(
            status="error", code="TOOL_ARG_ERROR",
            text="⚠️ TOOL_ARG_ERROR (vcs_read): invalid action, limit, or argument for this action.",
            meta={"operation_outcome": "completed_no_effect"},
        ))
    try:
        if _resolved_binding is None:
            # Internal callers receive the same pre-dispatch preparation as API
            # callers; there is no handler-local repository retargeting.
            from ouroboros.tools.tool_resolution import _build_builtin_target_binding

            binding = _build_builtin_target_binding(ctx, "vcs_read", {
                "root": root, "repository": repository, "path": path,
            })
        else:
            binding = _resolved_binding
        if binding.operation != "vcs" or binding.root not in {"active_workspace", "system_repo"}:
            raise ValueError("vcs_read requires a prepared VCS worktree binding")
        repo = binding.repository_path or binding.base_path
        literal = _literal_path(binding, path)
        if action in {"file", "blame"} and not literal:
            raise ValueError(f"{action} requires path")
        if action in _CONTENT_ACTIONS:
            if reason := _protected_content_reason(ctx, binding, literal, action):
                return _publish_tool_result(ctx, ToolResult(status="blocked", code="RESOURCE_POLICY_BLOCKED", text=reason))
        if action == "identity":
            output = _identity(repo)
        else:
            # Verify the selected worktree once before any history command.
            if pathlib.Path(_run_read_git(repo, ["rev-parse", "--show-toplevel"])).resolve(strict=False) != repo.resolve(strict=False):
                raise ValueError("repository must name the Git worktree root")
            if action == "log":
                cmd = ["log", f"--max-count={max_count}", "--format=fuller"]
                if ref:
                    cmd.append(_object(repo, ref, "commit"))
                if literal:
                    cmd.extend(["--", f":(literal){literal}"])
                output = _run_read_git(repo, cmd)
            elif action == "show":
                cmd = ["show", "--no-ext-diff", "--no-textconv", "--no-color", "--format=fuller", _object(repo, ref or "HEAD", "commit")]
                if literal:
                    cmd.extend(["--", f":(literal){literal}"])
                output = _run_read_git(repo, cmd)
            elif action == "file":
                output = _run_read_git(repo, ["show", "--no-ext-diff", "--no-textconv", f"{_object(repo, ref or 'HEAD', 'commit')}:{literal}"], preserve_output=True)
            elif action == "blame":
                output = _run_read_git(repo, ["blame", "--no-ext-diff", "--no-textconv", _object(repo, ref or "HEAD", "commit"), "--", literal])
            elif action == "refs":
                if ref and (not ref.startswith("refs/") or any(c in ref for c in "\x00\n\r :*?[\\")):
                    raise ValueError("refs filter must be a literal refs/ prefix")
                output = _run_read_git(repo, ["for-each-ref", "--format=%(refname) %(objectname) %(objecttype)", *( [ref] if ref else [] )])
            elif action == "rev_parse":
                output = _object(repo, ref or "HEAD", "object")
            else:
                output = _run_read_git(repo, ["merge-base", _object(repo, base, "commit"), _object(repo, head, "commit")])
        from ouroboros.tools.git_vcs_ops import _limit_git_output, _vcs_result

        return _publish_tool_result(ctx, ToolResult(
            status="ok", code="OK",
            text=_vcs_result(_limit_git_output(output, max_chars), binding, preserve_text=action == "file"),
        ))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return _publish_git_error(ctx, f"⚠️ GIT_ERROR: {_sanitize_git_error(str(exc))}")


def get_tools():
    """The history reader's public schema lives with its operation contract."""
    from ouroboros.tools.registry import ToolEntry

    return [ToolEntry("vcs_read", {
        "name": "vcs_read", "description": READ_DESCRIPTION,
        "parameters": {"type": "object", "required": ["action"], "properties": {
            "action": {"type": "string", "enum": sorted(_ACTIONS)},
            "root": {"type": "string", "enum": ["active_workspace", "system_repo"],
                     "default": "active_workspace"},
            "repository": {"type": "string", "default": "",
                           "description": "Git worktree root within root; omitted selects root itself. Not a file filter."},
            "path": {"type": "string", "default": "",
                     "description": "Literal repository-relative file/path filter; required for file and blame."},
            "ref": {"type": "string", "default": "",
                    "description": "Local revision (default HEAD), or a literal refs/ prefix for refs."},
            "base": {"type": "string", "default": "", "description": "First revision for merge_base only."},
            "head": {"type": "string", "default": "", "description": "Second revision for merge_base only."},
            "max_count": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20,
                          "description": "Maximum commits returned by log."},
            "max_chars": {"type": "integer", "minimum": 0, "default": 0,
                          "description": "Rendered output limit; zero keeps the complete result."},
        }},
    }, _vcs_read, is_code_tool=True, safety_policy="skip")]
