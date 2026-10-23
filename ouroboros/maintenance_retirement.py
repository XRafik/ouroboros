"""History-sized filesystem retirement, owned by the maintenance child.

A pass observes fixed directory stamps and current recovery facts. Time alone never
re-arms it; changed inputs, explicit repair (pending), or a new server generation do.
A source edited below an unchanged parent may wait for one of those facts. Retention
remains a minimum age, never an authorization to delete a live or unknown owner.
"""
from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import uuid

from ouroboros import maintenance_jobs, obligations, store

log = logging.getLogger(__name__)
JOB = "runtime_retirement"
STARTUP = "startup_recovery"
DIRECTORIES = ("task_trees", "services", "state/delegate_recovery",
               "state/delegate_recovery_transactions", "state/delegate_supervision", "state/skills",
               "state/code_intel", "state/extension_reconcile/failed", "uploads/screenshots", "uploads/views")


def record_startup(root, *, gaps):
    """Publish the recovery gate before a child may retire task sources. Missing means unknown."""
    with store.open_store(root, write=True) as txn:
        txn.set_meta(STARTUP, {"generation": uuid.uuid4().hex, "gaps": bool(gaps)})


def _inputs(root):
    from ouroboros.retention import get_gc_retention_days

    stamps = []
    for name in DIRECTORIES:
        try:
            info = (pathlib.Path(root) / name).lstat()
            stamps.append([info.st_ino, info.st_mtime_ns, info.st_size])
        except FileNotFoundError:
            stamps.append(None)
    with store.open_store(root, write=False) as txn:
        # Active recovery obligations only: never task bodies or completed history.
        recovery = {name: obligations.members_in(txn, name)
                    for name in ("nonterminal", "pending_drives", "unknowns")}
        token = hashlib.sha256(json.dumps(recovery, sort_keys=True).encode()).hexdigest()
        return {"directories": stamps, "recovery": token, "startup": txn.meta(STARTUP),
                "terminal": txn.meta(store.TERMINAL_WRITES), "retention": get_gc_retention_days()}


def due(root, row, facts, child):
    return row.get("state") == "pending" or row.get("inputs") != _inputs(root)


def run(root, should_stop):
    from ouroboros.code_intelligence import prune_stale_code_intel_roots
    from ouroboros.delegate_state_sweep import sweep_settled_delegate_state
    from ouroboros.extension_reconcile_queue import prune_failed_reconcile_markers
    from ouroboros.headless import prune_task_trees
    from ouroboros.skill_uninstall_state import sweep_uninstalled_skill_state
    from ouroboros.startup_task_files import startup_tree_exclusions
    from ouroboros.tools.services import prune_service_logs
    from ouroboros.utils import append_jsonl, utc_now_iso

    inputs, reports, errors = _inputs(root), {}, []
    steps = [("delegate_state", sweep_settled_delegate_state),
             ("skill_state", sweep_uninstalled_skill_state), ("code_intel", prune_stale_code_intel_roots),
             ("failed_reconcile", prune_failed_reconcile_markers), ("agent_media", prune_agent_media_uploads)]
    # Read the durable gate again immediately before source retirement. A fresh child
    # must never substitute its empty memory for the server's recovery result.
    with store.open_store(root, write=False) as txn:
        startup = txn.meta(STARTUP)
    if isinstance(startup, dict) and startup.get("gaps") is False and not should_stop():
        exclusions = startup_tree_exclusions(root)
        if exclusions is not None:
            steps[:0] = [("task_trees", lambda root: prune_task_trees(root, exclude_root_ids=exclusions)),
                         ("services", prune_service_logs)]
    for name, retire in steps:
        if should_stop():
            break
        try:
            report = retire(root) or {}
            reports[name] = report
            if report.get("errors"):
                errors.append(name)
        except Exception:
            errors.append(name)
            log.warning("%s retirement failed; sources stay owed", name, exc_info=True)
    state = "pending" if should_stop() else "failed" if errors else "done"
    # Keep the initial observation: a racing new artifact or recovery fact remains due.
    maintenance_jobs.record(root, JOB, state=state, inputs=inputs, errors=errors)
    if errors or any(report.get(key) for report in reports.values()
                     for key in ("removed", "swept", "restored", "deleted_dirs", "deleted_files")):
        append_jsonl(pathlib.Path(root) / "logs/events.jsonl",
                     {"ts": utc_now_iso(), "type": "runtime_retirement", "reports": reports, "errors": errors})
    return {"state": state, "items": len(reports)}


def prune_agent_media_uploads(
    drive_root: pathlib.Path,
    retention_days: "int | None" = None,
    *,
    now: "float | None" = None,
) -> dict:
    """Age-prune AGENT-generated media under uploads/ (CPL4-C21, owner 6A).

    Only ``uploads/screenshots/`` (browser tool) and ``uploads/views/``
    (view_image durable copies) follow GC retention — owner attachments live
    in the uploads/ ROOT and are owner-explicit-delete only, untouched here.
    Readers already skip missing files (the eviction placeholder only formats
    a re-view hint), so a pruned screenshot degrades to a stale hint, never
    an error. Fail-soft per file.

    CONTAINED (audit #15-13): the sweep deletes only REGULAR FILES that live
    inside the real family directory. ``is_file()``/``stat()`` follow symlinks,
    so a symlinked ``uploads/screenshots`` — or a single symlink inside it —
    made an age sweep of the drive unlink old files anywhere on the host. Both
    shapes are now skipped by ``lstat`` and counted, never followed.
    """
    import stat as stat_module

    from ouroboros.retention import age_cutoff, get_gc_retention_days

    if retention_days is None:
        retention_days = get_gc_retention_days()
    cutoff = age_cutoff(retention_days, now)
    report: dict = {"removed": 0, "kept": 0, "skipped": 0, "errors": 0}
    for family in ("screenshots", "views"):
        family_dir = pathlib.Path(drive_root) / "uploads" / family
        try:
            if family_dir.is_symlink():
                report["skipped"] += 1  # the whole family points out of the drive
                continue
            entries = sorted(family_dir.iterdir())
        except OSError:
            continue
        for path in entries:
            try:
                info = path.lstat()
                if not stat_module.S_ISREG(info.st_mode):
                    report["skipped"] += 1  # symlink, directory or special file
                    continue
                if info.st_mtime >= cutoff:
                    report["kept"] += 1
                    continue
                path.unlink()
                report["removed"] += 1
            except OSError:
                report["errors"] += 1
    return report


