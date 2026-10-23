"""Portable merge qualification and exact-range GitHub observations.

The commit trailer is evidence, never approval. Author declarations remain labelled;
missing executions stay unknown. Fetching checks consult GitHub, passive readers do not.
No prose is classified: older commit bodies reach the letter's author unchanged.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

TRAILER = "Ouroboros-Qualification: "
CHECKS = ("full_battery", "cost_contract")
STATES = ("passed", "failed", "not_run", "unknown")


def merge_qualification(review: dict, checks: list | None = None) -> dict:
    declared = {row["name"]: {**row, "source": "author_declared"} for row in checks or []}
    for name in CHECKS:
        declared.setdefault(name, {"name": name, "status": "unknown", "source": "missing",
                                   "detail": "No execution evidence was supplied."})
    record = review.get("record") or {}
    return {"schema": 1, "checks": list(declared.values()),
            "review": {"observed": (record.get("verdict") or {}).get("aggregate", "unknown"),
                       "declared": (review.get("declared") or {}).get("verdict", "unknown")},
            "post_merge": {"status": "not_run", "detail": "The post-merge check follows this merge."}}


def commit_summary(qualification: dict) -> str:
    lines = ["Ouroboros qualification receipt (declarations are not host-observed PASS):"]
    for row in qualification["checks"]:
        lines.append(f"- {row['name']}: {row['status']} ({row['source']}); {row.get('detail') or 'no detail supplied'}")
    review = qualification["review"]
    lines += [f"- Review: observed {review['observed']}; author declared {review['declared']}",
              "- Post-merge check: not run yet.", TRAILER + json.dumps(qualification, ensure_ascii=False)]
    return "\n".join(lines)


def commit_qualification(body: str) -> dict | None:
    for line in reversed(body.splitlines()):
        if line.startswith(TRAILER):
            try:
                value = json.loads(line[len(TRAILER):])
                if (isinstance(value, dict) and value.get("schema") == 1 and isinstance(value.get("checks"), list)
                        and isinstance(value.get("review", {}), dict) and all(
                            isinstance(row, dict) and isinstance(row.get("name"), str)
                            and row.get("status") in STATES and isinstance(row.get("detail", ""), str)
                            for row in value["checks"])):
                    return value
            except ValueError:
                pass
    return None


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                  "User-Agent": "Ouroboros-update-check"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _missing_runs(commits: list[dict], runs: dict) -> list[str]:
    """First-parent order is newest first; completed checks cover skipped pushes.

    Match post_merge_check.choose_base: cancelled/skipped runs are not coverage.
    Keep direct observations, including earlier reds, beside inferred coverage.
    """
    for run in runs.values():
        run.pop("covered_shas", None)
    covering, missing = None, []
    for commit in commits:
        sha = commit["sha"]
        run = runs.get(sha)
        if run:
            if run.get("status") == "completed" and run.get("conclusion") in ("success", "failure"):
                covering = run
        elif covering is not None:
            covering.setdefault("covered_shas", []).append(sha)
        else:
            missing.append(sha)
    return sorted(missing)


def post_merge_checks(commits: list[dict], repo_url: str, *, get_json=None) -> dict:
    """Read runs for first-parent integrations, newest first, including squash.

    Stop when every integration has an observation or later completed coverage,
    or history ends. A physical 10-page response budget stays disclosed.
    Public GitHub needs no credential. Offline/rate-limit failures remain unknown.
    """
    if not commits:
        return {"status": "observed", "runs": [], "missing_shas": []}
    get_json = get_json or _get_json
    parsed = urllib.parse.urlparse(repo_url)
    parts = parsed.path.removesuffix(".git").strip("/").split("/")
    if parsed.hostname != "github.com" or len(parts) != 2:
        return {"status": "unavailable", "reason": "The update source has no supported GitHub check reader.",
                "runs": [], "missing_shas": sorted(c["sha"] for c in commits)}
    wanted = {c["sha"] for c in commits}
    runs = {}
    complete = False
    try:
        for page in range(1, 11):
            data = get_json(f"https://api.github.com/repos/{'/'.join(parts)}/actions/workflows/"
                            f"post-merge.yml/runs?per_page=100&page={page}")
            rows = data["workflow_runs"]
            for row in rows:
                sha = row.get("head_sha")
                if sha in wanted and sha not in runs:
                    runs[sha] = {"sha": sha, "status": row.get("status"), "conclusion": row.get("conclusion"),
                                 "url": row.get("html_url"), "run_id": row.get("id"),
                                 "attempt": row.get("run_attempt")}
            missing = _missing_runs(commits, runs)
            if len(rows) < 100 or not missing:
                complete = True
                break
    except Exception as exc:
        return {"status": "unavailable", "reason": type(exc).__name__, "runs": list(runs.values()),
                "missing_shas": _missing_runs(commits, runs)}
    return {"status": "observed" if complete else "partial", "runs": list(runs.values()),
            "missing_shas": missing,
            "reason": "No matching run is not a passing check." if complete else "GitHub response page budget reached."}


def range_qualification(material: dict, repo_url: str) -> dict:
    commits = material.get("first_parent_commits", material.get("commits")) or []
    return {"base_sha": material["base_sha"], "target_sha": material["target_sha"],
            "commits": [{"sha": c["sha"], "subject": c["subject"],
                         "receipt": c.get("qualification", commit_qualification(c.get("body") or "")),
                         "body_read": c.get("body_read", True)}
                        for c in commits],
            "github": post_merge_checks(commits, repo_url)}


def refresh_qualification(authored: dict, repo_url: str, *, previous: dict | None = None) -> tuple[dict, bool]:
    """Refresh facts without making an outage erase observations or buy prose.

    The boolean names new check evidence relative to the letter's authoring input.
    Availability is shown separately, with the latest retained observations.
    """
    if not previous or any(previous.get(k) != authored.get(k) for k in ("base_sha", "target_sha")):
        previous = authored
    github = post_merge_checks(authored["commits"], repo_url)
    if github.get("status") in ("unavailable", "partial"):
        runs = {r["sha"]: dict(r) for r in previous.get("github", {}).get("runs", [])}
        runs.update({r["sha"]: dict(r) for r in github.get("runs", [])})
        github = {**github, "missing_shas": _missing_runs(authored["commits"], runs), "runs": list(runs.values())}
    old = authored.get("github") or {}
    changed = ({r["sha"]: r for r in github.get("runs", [])} != {r["sha"]: r for r in old.get("runs", [])}
               or github.get("missing_shas", []) != old.get("missing_shas", []))
    return {**authored, "github": github}, changed


def preflight_description(plan: dict, *, drive_root=None) -> dict:
    """Read the saved description for the exact pins; never fetch, write or author."""
    from ouroboros import update_letter as letter

    base, target = str(plan.get("base_sha") or ""), str(plan.get("target_sha") or "")
    if not base or not target:
        return {"letter": None, "qualification": None}
    record = letter.read_record(drive_root)
    view = letter.project_letter(record, head_sha=base, latest_sha=target)
    if view and not view["description_current"]:
        view = {**view, "text": ""}
    qualification = (record or {}).get("qualification")
    if qualification and (qualification.get("base_sha"), qualification.get("target_sha")) != (base, target):
        qualification = None
    return {"letter": view, "qualification": qualification}
