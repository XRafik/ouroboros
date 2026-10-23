"""Eligibility of mechanical collection, separate from the custody it still owes.

The receipt lives on RunCustody. A terminal revision, binding or observed named-source
change earns work; a clock does not. Transient failures may try once in a new body/child
generation. Readers disclose debt without requesting another attempt.
"""
from __future__ import annotations

import copy
import uuid

POLICY = "immutable-named-evidence-v1"
GENERATION = uuid.uuid4().hex


def capture_required(entry):
    return (entry.mode != "plan" and not entry.patch_disposed and not entry.superseded_by
            and bool(entry.execution_root or entry.resource_ref.get("workspace_kind") == "directory"))


def named_required(entry):
    return (capture_required(entry) and bool(entry.snapshot_id and entry.execution_root)
            and entry.authority_source != "skill_payload"
            and entry.resource_ref.get("workspace_kind") != "directory")


def inputs(entry):
    """Only addressed facts: never stat a snapshot or decode a summary to decide a tick."""
    return {**{key: copy.deepcopy(getattr(entry, key)) for key in (
        "run_id", "invocation_id", "snapshot_id", "capture_id", "continuation_of", "superseded_by",
        "execution_root", "baseline_sha", "authority_source", "resource_ref", "mode")},
        "terminal_sha": entry.terminal_source.get("sha256"), "policy": POLICY,
        "named_source": copy.deepcopy(entry.named_evidence.get("inputs") or {}),
        "named_status": entry.named_evidence.get("status"),
        "output_sha": entry.output_sha, "output_complete": entry.output_complete,
        "output_terminal_sha": entry.output_terminal_sha, "patch_captured": entry.patch_captured,
        "patch_disposed": entry.patch_disposed, "ledger_recorded": entry.ledger_recorded, "settled": entry.settled}


def collection_due(entry, *, generation=GENERATION, recapture=False):
    """One rule for scheduling and collection. Missing/malformed outcomes earn one attempt."""
    if entry is None or entry.review_owned or not entry.terminal_source:
        return False
    attempt = entry.collection_attempt
    return (recapture or not isinstance(attempt, dict) or not attempt.get("inputs")
            or attempt["inputs"] != inputs(entry)
            or (attempt.get("retry") == "transient" and attempt.get("generation") != generation))


def record_attempt(root, entry, *, generation=GENERATION, retry="", errors=()):
    from ouroboros import delegate_custody as custody

    outcome = {"inputs": inputs(entry), "generation": generation, "retry": retry, "errors": list(errors)}
    if entry.collection_attempt == outcome:
        return True
    return custody.emit(root, custody.COLLECTION_ATTEMPTED,
                        {"run_id": entry.run_id, "task_id": entry.task_id, "outcome": outcome})
