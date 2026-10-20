"""Internal, policy-bounded task trace adapter for ``query_records``.

This is deliberately not a tool entry.  Pages expose physical source
observations, never page-local reconstructions of a logical invocation.  A
cursor pins the byte horizon of every selected rotated JSONL source; call and
authored-output source bytes are read separately by a digest-pinned identity.

Only retained redacted projections are source material.  A manifest whose
authoritative payload is raw is useful only when it also publishes a redacted
projection; hidden/native reasoning is therefore never recovered by fallback.
"""
from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from ouroboros.jsonl_tail import JsonlChainSnapshot
from ouroboros.task_results import load_task_result, validate_task_id
from ouroboros.task_status import SETTLED_STATUSES
from ouroboros.tool_call_log import (
    CALL_SETTLED,
    CALL_STARTED,
    CALL_WAIT_ENDED,
    logical_calls,
)

TRACE_STREAMS = ("tools", "authored_outputs", "errors", "events")
TRACE_OPERATIONS = ("list", "read_call", "read_authored_output")
_LOGS_BY_STREAM = {
    "tools": (("tools", ("logs", "tools.jsonl")),),
    "errors": (
        ("events", ("logs", "events.jsonl")),
        ("tools", ("logs", "tools.jsonl")),
        ("supervisor", ("logs", "supervisor.jsonl")),
    ),
    "events": (
        ("events", ("logs", "events.jsonl")),
        ("supervisor", ("logs", "supervisor.jsonl")),
    ),
}
_PAGE_SCAN_BYTES = 256 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_CALL_MANIFEST_BYTES = 16 * 1024 * 1024
_TOOL_CALL_TYPES = ("tool_call", "tool_timeout")
_DISPATCH_CALL_TYPES = ("tool_dispatch",)
_AUTHORED_CALL_TYPES = ("llm_response",)


class TaskTraceArgumentError(ValueError):
    """A caller-correctable trace address/cursor error."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _trace_arguments(task_id: str, operation: str, presence_scope: str = "", **values: Any) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "form": "task_trace", "task_id": task_id, "operation": operation, **values,
    }
    if presence_scope:
        arguments["presence_scope"] = presence_scope
    return arguments


def _status_root(ctx: Any) -> tuple[Path, str]:
    from ouroboros.tool_access import canonical_data_root

    metadata = getattr(ctx, "task_metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    native = str(metadata.get("native_data_root") or "").strip()
    # A native review is a frozen plane.  It never falls through to a live
    # canonical root when its retained source is absent.
    root = Path(native or canonical_data_root(ctx)).resolve()
    return root, "native_pin" if native else "canonical"


def _lineage_contains(root: Path, ancestor: str, target: str) -> bool:
    from ouroboros import store

    try:
        with store.open_store(root, write=False) as txn:
            row = txn.conn.execute(
                """WITH RECURSIVE lineage(task_id) AS (
                       SELECT task_id FROM tasks WHERE task_id=? UNION
                       SELECT t.task_id FROM tasks t JOIN lineage p ON t.parent_task_id=p.task_id)
                   SELECT 1 FROM lineage WHERE task_id=?""",
                (ancestor, target),
            ).fetchone()
        return bool(row)
    except Exception:
        return False


def _authorize(ctx: Any, root: Path, task_id: str, presence_scope: str) -> None:
    from ouroboros.presence_authority import (
        PRESENCE_OWN_WORK_SCOPE,
        presence_caller_binding,
        presence_work_refusal,
    )
    from ouroboros.tools.recent_tasks import _restricted_actor

    actor = validate_task_id(str(getattr(ctx, "task_id", "") or ""))
    binding = presence_caller_binding(ctx)
    if binding is not None:
        if str(presence_scope or "") != PRESENCE_OWN_WORK_SCOPE:
            raise PermissionError(
                "task_trace from a Presence turn requires presence_scope=own_binding; "
                "a selected query_records capability does not widen task scope"
            )
        refusal = presence_work_refusal(ctx, task_id, drive_root=root, same_tree=True)
        if refusal:
            raise PermissionError(refusal)
        # Presence authority is its binding-scoped task relation (including
        # independent work started from another conversation of that binding),
        # not delegated-child lineage.  Passing that exact check is sufficient.
        return
    elif presence_scope:
        raise TaskTraceArgumentError("presence_scope is valid only for a Presence binding")

    if not _restricted_actor(ctx) or task_id == actor:
        return
    inherited = False
    try:
        from ouroboros.owner_quiz import question_task_owned_by

        inherited = question_task_owned_by(root, task_id, actor)
    except Exception:
        inherited = False
    if not _lineage_contains(root, actor, task_id) and not inherited:
        raise PermissionError(
            "task_trace target is outside this delegated actor's own, descendant, or recorded inherited work"
        )


def _admit_source(ctx: Any, target: Path, *, boundary: Path) -> None:
    """Apply the existing resource-read admission to one physical source.

    Task lineage chooses *whose* trace may be addressed.  It is not file-read
    authority: every store, log, manifest, loose CAS member, and pack still
    passes the same resource/Presence/protected-artifact decision as read_file
    and query_data.  ``boundary`` also keeps a native pin and an execution
    replica on the physical plane selected by the host.
    """
    from ouroboros.tools.query_data import _read_refusal

    path = Path(target).resolve(strict=False)
    root = Path(boundary).resolve(strict=False)
    if not path.is_relative_to(root):
        raise PermissionError("task_trace source escapes its selected physical data plane")
    refusal = _read_refusal(ctx, path)
    if refusal:
        raise PermissionError(
            f"task_trace source is not readable by this actor ({refusal}); no grant is inferred"
        )


def _admit_authorization_sources(ctx: Any, root: Path, task_id: str) -> None:
    """Admit every physical source authorization may consult before it does so."""
    from ouroboros import store
    from ouroboros.presence_authority import presence_caller_binding

    _admit_source(ctx, root / store.STORE_REL, boundary=root)
    # Presence ownership falls back to the persisted queue when the store has
    # no binding carrier.  Admission must precede that conditional lookup; an
    # authorization read cannot bootstrap its own file authority.
    if presence_caller_binding(ctx) is not None:
        from ouroboros.dialogue_provenance import presence_metadata_binding
        from ouroboros.task_results import load_task_result

        try:
            stored = load_task_result(root, task_id)
        except (OSError, ValueError, store.StoreError):
            stored = None
        contract = stored.get("task_contract") if isinstance(stored, Mapping) else None
        uses_queue = (
            not isinstance(stored, Mapping) or not stored
            or (presence_metadata_binding(stored.get("metadata")) is None
                and not (isinstance(contract, Mapping) and "capability_ceiling" in contract))
        )
        if uses_queue:
            _admit_source(ctx, root / "state" / "queue_snapshot.json", boundary=root)


def _roots(ctx: Any, canonical: Path, task_id: str, *, native: bool) -> List[Tuple[str, Path]]:
    from ouroboros.task_custody import own_child_drives

    rows: List[Tuple[str, Path]] = [("canonical", canonical)]
    # A native review's data root is already the complete pinned plane.  Do not
    # consult child-drive fields or live execution layouts, even if a stale pin
    # records an absolute drive that still exists on the host.
    if native:
        return rows
    if not native and task_id == str(getattr(ctx, "task_id", "") or ""):
        local = Path(ctx.drive_root).resolve()
        if local != canonical:
            rows.insert(0, ("caller", local))
    try:
        children = own_child_drives(canonical, task_id)
    except Exception:
        children = []
    for index, path in enumerate(children):
        resolved = Path(path).resolve()
        if all(resolved != held for _label, held in rows):
            rows.insert(index, (f"execution:{index}", resolved))
    return rows


def _physical_record(ctx: Any, roots: Iterable[Tuple[str, Path]], task_id: str) -> tuple[Dict[str, Any], Path]:
    from ouroboros import store

    ordered = list(roots)
    candidates: List[tuple[str, int, Dict[str, Any], Path]] = []

    def load(label: str, order: int, root: Path) -> tuple[str, int, Dict[str, Any], Path] | None:
        try:
            _admit_source(ctx, root / store.STORE_REL, boundary=root)
            row = load_task_result(root, task_id, strict=True)
        except PermissionError:
            raise
        except ValueError as exc:
            if label == "canonical":
                raise RuntimeError(
                    "canonical task result failed identity or schema verification"
                ) from exc
            return None
        except OSError:
            return None
        if not isinstance(row, dict):
            return None
        return label, order, row, root

    # A settled canonical row is the selected final authority.  No amount of
    # trace richness, terminal metadata, or an older completed execution copy
    # can replace it, and stale stores need not be opened after that decision.
    canonical_spec = next(((order, root) for order, (label, root) in enumerate(ordered)
                           if label == "canonical"), None)
    canonical = load("canonical", *canonical_spec) if canonical_spec is not None else None
    if canonical is not None:
        candidates.append(canonical)
        if str(canonical[2].get("status") or "").strip().lower() in SETTLED_STATUSES:
            _label, _order, record, root = canonical
            return record, root

    # Before canonical settlement, the first host-ordered settled execution
    # copy may be the only physical completion.  Otherwise retain canonical,
    # then the first readable replica; trace richness never affects the choice.
    chosen = None
    for order, (label, root) in enumerate(ordered):
        if label == "canonical":
            continue
        candidate = load(label, order, root)
        if candidate is None:
            continue
        candidates.append(candidate)
        if str(candidate[2].get("status") or "").strip().lower() in SETTLED_STATUSES:
            chosen = candidate
            break
    if not candidates:
        raise FileNotFoundError(f"physical task {task_id} is unavailable in the selected data plane")
    chosen = chosen or canonical or candidates[0]
    _label, _order, record, root = chosen
    return record, root


def _manifest_rows(record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    trace = record.get("trace_refs") if isinstance(record.get("trace_refs"), dict) else {}
    rows: List[Dict[str, Any]] = []
    for item in trace.get("tool_call_refs") or []:
        if isinstance(item, dict) and isinstance(item.get("manifest_ref"), dict):
            rows.append({"class": "tool", "ref": dict(item["manifest_ref"])})
    for item in trace.get("llm_call_refs") or []:
        if not isinstance(item, dict):
            continue
        for field, call_class in (("request_ref", "llm_request"), ("response_ref", "llm_response")):
            if isinstance(item.get(field), dict):
                rows.append({"class": call_class, "ref": dict(item[field]), "llm": item})
    return rows


def _published_calls(record: Mapping[str, Any], task_id: str, presence_scope: str) -> List[Dict[str, Any]]:
    calls = []
    for row in _manifest_rows(record):
        # LLM requests are private inputs, and LLM responses have the narrower
        # authored-output projection below.  ``read_call`` is the exact tool-call
        # source reader, not a generic observability-manifest escape hatch.
        if row["class"] != "tool":
            continue
        ref = row["ref"]
        call_id, digest = str(ref.get("call_id") or ""), str(ref.get("sha256") or "")
        if not call_id or len(digest) != 64:
            continue
        calls.append({
            "call_id": call_id,
            "manifest_sha256": digest,
            "call_class": row["class"],
            "source_read": {
                "tool": "query_records",
                "arguments": _trace_arguments(
                    task_id, "read_call", presence_scope,
                    call_id=call_id, manifest_sha256=digest,
                ),
            },
        })
    return calls


def _has_authoritative_result(record: Mapping[str, Any]) -> bool:
    return str(record.get("status") or "").strip().lower() in SETTLED_STATUSES and "result" in record


def _authored_rows(record: Mapping[str, Any], task_id: str, presence_scope: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if _has_authoritative_result(record):
        answer = str(record.get("result") or "")
        rows.append({
            "authored_output_id": "authoritative_result",
            "selected": True,
            "selection_basis": "settled_physical_task_result",
            "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
            "terminal_origin": str(record.get("terminal_origin") or "unknown"),
            "source_read": {"tool": "query_records", "arguments": _trace_arguments(
                task_id, "read_authored_output", presence_scope,
                authored_output_id="authoritative_result",
            )},
        })
    for item in _manifest_rows(record):
        if item["class"] != "llm_response":
            continue
        ref, llm = item["ref"], item.get("llm") or {}
        call_id, digest = str(ref.get("call_id") or ""), str(ref.get("sha256") or "")
        if not call_id or len(digest) != 64:
            continue
        # The authored-output address carries the complete retained manifest
        # digest.  A display-length prefix is not an exact physical identity.
        output_id = f"response:{call_id}:{digest}"
        rows.append({
            "authored_output_id": output_id,
            # A draft remains a draft even if its bytes happen to equal the
            # selected result.  Selection never follows latest/longest/equal.
            "selected": False,
            "selection_basis": "observed_llm_response",
            "llm_call_id": str(llm.get("llm_call_id") or ""),
            "physical_attempt": llm.get("attempt", "unknown_legacy"),
            "round": llm.get("round"),
            "model": llm.get("resolved_model") or llm.get("model"),
            "provider": llm.get("provider"),
            "manifest_sha256": digest,
            "source_read": {"tool": "query_records", "arguments": _trace_arguments(
                task_id, "read_authored_output", presence_scope,
                authored_output_id=output_id,
            )},
        })
    return rows


def _source_spec(roots: Iterable[Tuple[str, Path]], stream: str) -> List[Dict[str, Any]]:
    rows = []
    for root_label, root in roots:
        for source, relative in _LOGS_BY_STREAM[stream]:
            identity = hashlib.sha256(f"{root_label}:{source}:{root}".encode("utf-8")).hexdigest()[:24]
            rows.append({"id": identity, "root_label": root_label, "root": root,
                         "source": source, "path": root.joinpath(*relative)})
    return rows


def _admitted_snapshot(ctx: Any, spec: Mapping[str, Any], *, upper: int | None = None) -> JsonlChainSnapshot:
    from ouroboros.utils import jsonl_archive_segments

    root, live = Path(spec["root"]), Path(spec["path"])
    _admit_source(ctx, live, boundary=root)
    archive = live.parent.parent / "archive"
    _admit_source(ctx, archive, boundary=root)
    # Admit every currently named generation before JsonlChainSnapshot opens
    # it.  Re-check captured entries after construction so a generation that
    # rotated during discovery still cannot be read under the live name's grant.
    for segment in jsonl_archive_segments(live, strict=True):
        _admit_source(ctx, segment, boundary=root)
    snapshot = JsonlChainSnapshot(live, upper=upper, strict=True)
    for segment, _stat, _was_live in snapshot.entries:
        _admit_source(ctx, Path(segment), boundary=root)
    return snapshot


def _published_cursor_state(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "offset": 0,
        "upper": len(rows),
        "view": hashlib.sha256(_canonical(rows)).hexdigest(),
    }


def _fresh_cursor(ctx: Any, task_id: str, stream: str, specs: List[Dict[str, Any]],
                  published_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    positions = []
    for spec in specs:
        snapshot = _admitted_snapshot(ctx, spec)
        positions.append({
            "id": spec["id"], "offset": 0, "upper": snapshot.upper,
            "row_continuation": False,
        })
    calls = _published_cursor_state(published_calls) if stream == "tools" else None
    view = hashlib.sha256(_canonical({"task_id": task_id, "stream": stream,
                                      "sources": [row["id"] for row in positions],
                                      **({"published_calls": calls["view"]} if calls else {})})).hexdigest()
    return {"v": 2, "task_id": task_id, "stream": stream, "view": view, "sources": positions,
            **({"published_calls": calls} if calls else {})}


def _validated_cursor(ctx: Any, value: Any, task_id: str, stream: str, specs: List[Dict[str, Any]],
                      published_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    if value is None:
        return _fresh_cursor(ctx, task_id, stream, specs, published_calls)
    expected_keys = {"v", "task_id", "stream", "view", "sources"}
    if stream == "tools":
        expected_keys.add("published_calls")
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise TaskTraceArgumentError("task_trace cursor must be the exact object returned by this stream")
    version = value.get("v")
    if version not in {1, 2} or value.get("task_id") != task_id or value.get("stream") != stream:
        raise TaskTraceArgumentError("task_trace cursor task/stream/version mismatch")
    sources = value.get("sources")
    if not isinstance(sources, list) or len(sources) != len(specs):
        raise TaskTraceArgumentError("task_trace cursor no longer covers the selected physical sources; restart without it")
    expected_ids = [spec["id"] for spec in specs]
    if [row.get("id") if isinstance(row, dict) else None for row in sources] != expected_ids:
        raise TaskTraceArgumentError("task_trace cursor source identity changed; restart without it")
    calls = _published_cursor_state(published_calls) if stream == "tools" else None
    expected_view = hashlib.sha256(_canonical({"task_id": task_id, "stream": stream,
                                               "sources": expected_ids,
                                               **({"published_calls": calls["view"]} if calls else {})})).hexdigest()
    if value.get("view") != expected_view:
        raise TaskTraceArgumentError("task_trace cursor view mismatch")
    out = json.loads(json.dumps(value))
    for row in out["sources"]:
        expected_position = ({"id", "offset", "upper"} if version == 1 else
                             {"id", "offset", "upper", "row_continuation"})
        if (set(row) != expected_position or type(row["offset"]) is not int
                or type(row["upper"]) is not int
                or (version == 2 and type(row["row_continuation"]) is not bool)):
            raise TaskTraceArgumentError("task_trace cursor source position is invalid")
        if not 0 <= row["offset"] <= row["upper"]:
            raise TaskTraceArgumentError("task_trace cursor source position is outside its captured horizon")
        row.setdefault("row_continuation", False)
    out["v"] = 2
    if stream == "tools":
        position = out.get("published_calls")
        if (not isinstance(position, dict) or set(position) != {"offset", "upper", "view"}
                or type(position.get("offset")) is not int or type(position.get("upper")) is not int
                or not 0 <= position["offset"] <= position["upper"]
                or position["upper"] != calls["upper"] or position.get("view") != calls["view"]):
            raise TaskTraceArgumentError(
                "task_trace cursor published-call horizon changed; restart without it"
            )
    return out


def _read_chunk(
    snapshot: JsonlChainSnapshot,
    start: int,
    max_bytes: int,
    *,
    row_continuation: bool = False,
) -> tuple[List[Tuple[int, int, Dict[str, Any]]], int, List[Dict[str, Any]], int, bool]:
    """Read complete JSONL rows without exceeding this page's physical allowance.

    A row longer than a whole page becomes an explicit gap.  Its remaining
    bytes are skipped over bounded cursor continuations, so neither this call
    nor a later page accumulates the row or mistakes its middle for new JSON.
    """
    if max_bytes <= 0 or start >= snapshot.upper:
        return [], start, [], 0, row_continuation
    index = bisect_right(snapshot.ends, start)
    if index >= len(snapshot.entries):
        return [], snapshot.upper, [], 0, False
    _base, segment_end = snapshot.segment(index)
    segment_end = min(segment_end, snapshot.upper)
    end = min(segment_end, start + min(_READ_CHUNK_BYTES, max_bytes))
    raw = snapshot._read(start, end)  # one retained, rotation-aware captured chain
    physical_read = len(raw)
    if row_continuation:
        newline = raw.find(b"\n")
        while newline < 0 and end < segment_end and len(raw) < max_bytes:
            extra_end = min(segment_end, end + min(_READ_CHUNK_BYTES, max_bytes - len(raw)))
            extra = snapshot._read(end, extra_end)
            physical_read += len(extra)
            newline = extra.find(b"\n")
            if newline >= 0:
                raw += extra
                break
            raw += extra
            end = extra_end
        if newline >= 0:
            # ``newline`` is relative to ``extra`` in the loop and to ``raw``
            # on the first read; normalize to the first delimiter in all bytes.
            advance = raw.find(b"\n") + 1
            return [], start + advance, [{
                "offset": start, "reason": "oversized_jsonl_row_continuation",
            }], physical_read, False
        at_segment_end = end >= segment_end
        return [], end, [{
            "offset": start,
            "reason": ("partial_line_at_captured_horizon" if at_segment_end
                       else "oversized_jsonl_row_continuation"),
        }], physical_read, not at_segment_end

    if end < segment_end and raw and not raw.endswith(b"\n"):
        # Extend only inside the caller's remaining physical allowance.  A
        # normal row crossing the 64 KiB working chunk is still preserved.
        while end < segment_end and not raw.endswith(b"\n") and len(raw) < max_bytes:
            extra_end = min(segment_end, end + min(_READ_CHUNK_BYTES, max_bytes - len(raw)))
            extra = snapshot._read(end, extra_end)
            physical_read += len(extra)
            newline = extra.find(b"\n")
            if newline >= 0:
                raw += extra[:newline + 1]
                end += newline + 1
                break
            raw += extra
            end = extra_end

    complete_end = raw.rfind(b"\n") + 1
    if complete_end < len(raw) and end < segment_end:
        if complete_end:
            # A row began late in this page.  Do not discard it merely because
            # the prior complete rows spent the allowance; retry it next page.
            raw_to_parse = raw[:complete_end]
            next_position = start + complete_end
            next_continuation = False
        elif max_bytes < _PAGE_SCAN_BYTES:
            # The page began before this call.  Leave the row at its boundary
            # so the next page can give it the complete page allowance.
            return [], start, [], physical_read, False
        else:
            # No delimiter in one complete page: the row itself is oversized.
            return [], end, [{
                "offset": start, "reason": "oversized_jsonl_row",
            }], physical_read, True
    else:
        raw_to_parse = raw
        next_position = start + len(raw)
        next_continuation = False
    rows: List[Tuple[int, int, Dict[str, Any]]] = []
    gaps: List[Dict[str, Any]] = []
    position = start
    for line in raw_to_parse.splitlines(keepends=True):
        line_start = position
        position += len(line)
        if not line.endswith(b"\n"):
            # At a captured live horizon this is not an observation yet.  The
            # cursor discloses and advances over those non-row bytes for this
            # immutable pass; a new pass can capture the completed append.
            gaps.append({"offset": line_start, "reason": "partial_line_at_captured_horizon"})
            continue
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            if line.strip():
                gaps.append({"offset": line_start, "reason": "malformed_jsonl"})
            continue
        if isinstance(value, dict):
            rows.append((line_start, position, value))
        else:
            gaps.append({"offset": line_start, "reason": "non_object_jsonl"})
    return rows, next_position, gaps, physical_read, next_continuation


def _is_target(row: Mapping[str, Any], task_id: str) -> bool:
    return str(row.get("task_id") or "") == task_id or str(row.get("subagent_task_id") or "") == task_id


def _is_error(row: Mapping[str, Any]) -> bool:
    kind = str(row.get("type") or "").lower()
    status = str(row.get("status") or "").lower()
    return bool(row.get("is_error") is True or "error" in kind or kind.endswith("failed")
                or status in {"error", "failed", "host_error"})


def _tool_observation(
    row: Mapping[str, Any], task_id: str, presence_scope: str,
) -> Dict[str, Any] | None:
    kind = str(row.get("type") or "")
    if kind not in {CALL_STARTED, CALL_SETTLED, CALL_WAIT_ENDED} and not row.get("tool"):
        return None
    # ``logical_calls`` is used only to recognize legacy identity.  Its state is
    # intentionally not exposed: one row/page cannot prove a complete call.
    normalized = logical_calls([dict(row)])
    legacy = bool(normalized and normalized[0].get("state") == "legacy")
    observation = {
        CALL_STARTED: "started",
        CALL_SETTLED: "settled",
        CALL_WAIT_ENDED: "wait_ended",
    }.get(kind, "legacy_settlement")
    ref = row.get("args_source_ref") if isinstance(row.get("args_source_ref"), Mapping) else {}
    source_call_id = str(ref.get("call_id") or "")
    source_digest = str(ref.get("sha256") or "")
    source_status = str(row.get("args_source_status") or "")
    dispatch_source: Dict[str, Any] = {}
    if (source_status == "ready" and source_call_id.startswith("tool_dispatch_")
            and re.fullmatch(r"[0-9a-f]{64}", source_digest)):
        dispatch_source = {
            "dispatch_source": {
                "call_id": source_call_id,
                "manifest_sha256": source_digest,
                "source_read": {
                    "tool": "query_records",
                    "arguments": _trace_arguments(
                        task_id, "read_call", presence_scope,
                        call_id=source_call_id, manifest_sha256=source_digest,
                    ),
                },
            },
        }
    elif source_status:
        dispatch_source = {"dispatch_source_status": source_status}
    return {
        "observation": observation,
        "invocation_id": str(row.get("invocation_id") or "") or None,
        "partial_group": True,
        "group_completeness": "not_asserted",
        "physical_attempt": row.get("task_attempt") if row.get("task_attempt") is not None else "unknown_legacy",
        "legacy_identity": legacy,
        "tool": str(row.get("tool") or ""),
        "tool_call_id": str(row.get("tool_call_id") or ""),
        "ts": str(row.get("ts") or ""),
        **({"execution_id": str(row["execution_id"])} if row.get("execution_id") else {}),
        **({"round_id": str(row["round_id"])} if row.get("round_id") else {}),
        **({"llm_call_id": str(row["llm_call_id"])} if row.get("llm_call_id") else {}),
        **({"status": str(row["status"])} if row.get("status") is not None else {}),
        **({"is_error": bool(row["is_error"])} if "is_error" in row else {}),
        **dispatch_source,
    }


def _event_observation(row: Mapping[str, Any], *, error: bool) -> Dict[str, Any]:
    return {
        "observation": "error" if error else "event",
        "event_type": str(row.get("type") or "event"),
        "ts": str(row.get("ts") or ""),
        "invocation_id": str(row.get("invocation_id") or "") or None,
        "partial_group": True,
        "group_completeness": "not_asserted",
        "physical_attempt": row.get("task_attempt") if row.get("task_attempt") is not None else "unknown_legacy",
        **({"tool": str(row["tool"])} if row.get("tool") else {}),
        **({"status": str(row["status"])} if row.get("status") is not None else {}),
        **({"error_code": str(row["error_code"])} if row.get("error_code") else {}),
        **({"execution_id": str(row["execution_id"])} if row.get("execution_id") else {}),
        **({"round_id": str(row["round_id"])} if row.get("round_id") else {}),
        # Error/message bodies, args, result previews and reasoning are not an
        # enumeration field.  Their presence is still an honest observation.
        **({"diagnostic_text_withheld": True} if any(key in row for key in ("error", "message", "result_preview", "args")) else {}),
    }


def _list_logs(ctx: Any, record: Mapping[str, Any], roots: List[Tuple[str, Path]], task_id: str,
               stream: str, cursor: Any, limit: int, plane: str,
               presence_scope: str) -> Dict[str, Any]:
    specs = _source_spec(roots, stream)
    published = _published_calls(record, task_id, presence_scope) if stream == "tools" else []
    held = _validated_cursor(ctx, cursor, task_id, stream, specs, published)
    observations: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    scanned = 0
    for index, spec in enumerate(specs):
        position = held["sources"][index]
        if position["offset"] >= position["upper"]:
            continue
        snapshot = _admitted_snapshot(ctx, spec, upper=position["upper"])
        while position["offset"] < position["upper"] and len(observations) < limit and scanned < _PAGE_SCAN_BYTES:
            rows, next_offset, found_gaps, consumed, next_continuation = _read_chunk(
                snapshot, position["offset"], _PAGE_SCAN_BYTES - scanned,
                row_continuation=position["row_continuation"],
            )
            scanned += consumed
            if next_offset <= position["offset"]:
                break
            resume_offset = next_offset
            resume_continuation = next_continuation
            for offset, row_end, raw in rows:
                if not _is_target(raw, task_id):
                    continue
                if stream == "tools":
                    projected = _tool_observation(raw, task_id, presence_scope)
                    if projected is None:
                        continue
                elif stream == "errors":
                    if not _is_error(raw):
                        continue
                    projected = _event_observation(raw, error=True)
                else:
                    projected = _event_observation(raw, error=False)
                observations.append({
                    **projected,
                    "source": {"source_id": spec["id"], "stream": spec["source"],
                               "root": spec["root_label"], "offset": offset},
                })
                if len(observations) >= limit:
                    # The chunk may hold later physical rows.  Resume at this
                    # observation's exact line end, not the chunk end, so a
                    # page boundary can split start / wait-end / settlement.
                    resume_offset = row_end
                    resume_continuation = False
                    break
            position["offset"] = resume_offset
            position["row_continuation"] = resume_continuation
            gaps.extend({"source_id": spec["id"], "source": spec["source"], **gap}
                        for gap in found_gaps if int(gap.get("offset") or 0) < resume_offset)
    call_page: List[Dict[str, Any]] = []
    call_page_start = 0
    if stream == "tools":
        call_position = held["published_calls"]
        call_page_start = call_position["offset"]
        remaining = max(0, limit - len(observations))
        call_page = published[call_page_start:call_page_start + remaining]
        call_position["offset"] += len(call_page)
    source_more = any(row["offset"] < row["upper"] for row in held["sources"])
    call_more = bool(stream == "tools" and held["published_calls"]["offset"]
                     < held["published_calls"]["upper"])
    has_more = source_more or call_more
    return {
        "task_id": task_id,
        "stream": stream,
        "semantics": "physical_observations",
        "logical_grouping": "not_performed",
        "observations": observations,
        "published_calls": call_page,
        "cursor": held if has_more else None,
        "has_more": has_more,
        "coverage": {
            "plane": plane,
            "source_bound_horizon": True,
            "source_order": [{"source_id": spec["id"], "stream": spec["source"],
                              "root": spec["root_label"]} for spec in specs],
            "scanned_bytes_this_page": scanned,
            "scan_byte_limit": _PAGE_SCAN_BYTES,
            "gaps": gaps,
            **({"published_call_page": {
                "offset": call_page_start,
                "shown": len(call_page),
                "total": held["published_calls"]["upper"],
                "source": "physical_task_result_trace_refs",
            }} if stream == "tools" else {}),
        },
    }


def _list_authored(
    record: Mapping[str, Any], task_id: str, cursor: Any, limit: int,
    plane: str, presence_scope: str,
) -> Dict[str, Any]:
    rows = _authored_rows(record, task_id, presence_scope)
    fingerprint = hashlib.sha256(_canonical(rows)).hexdigest()
    if cursor is None:
        offset = 0
    elif (not isinstance(cursor, dict) or set(cursor) != {"v", "task_id", "stream", "view", "offset"}
          or cursor.get("v") != 1 or cursor.get("task_id") != task_id
          or cursor.get("stream") != "authored_outputs" or cursor.get("view") != fingerprint
          or type(cursor.get("offset")) is not int or not 0 <= cursor["offset"] <= len(rows)):
        raise TaskTraceArgumentError("authored_outputs cursor is invalid or its physical result changed; restart without it")
    else:
        offset = cursor["offset"]
    page = rows[offset:offset + limit]
    next_offset = offset + len(page)
    return {
        "task_id": task_id, "stream": "authored_outputs", "semantics": "published_authored_outputs",
        "outputs": page,
        "cursor": ({"v": 1, "task_id": task_id, "stream": "authored_outputs",
                    "view": fingerprint, "offset": next_offset} if next_offset < len(rows) else None),
        "has_more": next_offset < len(rows),
        "coverage": {"plane": plane, "physical_task_result_fingerprint": fingerprint,
                     "selection_rule": (
                         "settled stored authoritative result only; observed responses remain drafts"
                         if _has_authoritative_result(record)
                         else "no settled authoritative result; observed responses remain drafts"
                     )},
    }


def _find_manifest(record: Mapping[str, Any], call_id: str, digest: str, *, call_class: str) -> Dict[str, Any]:
    matches = [row for row in _manifest_rows(record)
               if str(row["ref"].get("call_id") or "") == call_id
               and str(row["ref"].get("sha256") or "") == digest
               and row["class"] == call_class]
    if not matches:
        raise PermissionError(
            f"{call_class} identity is not published by this physical task's retained trace refs"
        )
    return matches[0]


def _projection_bytes(ctx: Any, root: Path, task_id: str,
                      published: Mapping[str, Any], *,
                      call_types: Tuple[str, ...]) -> tuple[bytes, Dict[str, Any]]:
    from ouroboros.observability import read_blob_ref, read_call_manifest_ref

    ref = dict(published["ref"])
    try:
        manifest = read_call_manifest_ref(
            root, ref, task_id=task_id, max_bytes=_CALL_MANIFEST_BYTES,
            admit=lambda physical: _admit_source(ctx, physical, boundary=root),
            call_types=call_types,
        )
    except PermissionError:
        raise
    except FileNotFoundError as exc:
        raise FileNotFoundError("retained call manifest is unavailable") from exc
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("retained call manifest failed identity or digest verification") from exc
    projection = manifest.get("redacted_projection_ref")
    if not isinstance(projection, dict) or not projection:
        # Old manifests may have only one already-redacted authoritative blob.
        # A raw KEEP_RAW payload is never such a fallback.
        projection = manifest.get("full_payload_ref") if manifest.get("full_payload_redacted") is True else None
    if not isinstance(projection, dict) or not projection:
        raise FileNotFoundError("retained call has no redacted projection; raw payload is not readable through task_trace")
    try:
        raw = read_blob_ref(root, projection, expected_kind=str(projection.get("kind") or "json"),
                            max_bytes=16 * 1024 * 1024, raw_bytes=True,
                            admit=lambda physical: _admit_source(ctx, physical, boundary=root))
    except PermissionError:
        raise
    except FileNotFoundError as exc:
        raise FileNotFoundError("retained redacted call projection is unavailable") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError("retained redacted call projection failed digest verification") from exc
    return raw, manifest


def _range_projection(text: str, *, start: Any, end: Any, source: Dict[str, Any]) -> Dict[str, Any]:
    encoded = text.encode("utf-8")
    out = {**source, "source_sha256": hashlib.sha256(encoded).hexdigest(), "complete_chars": len(text)}
    if start is None and end is None:
        return out
    if type(start) is not int or type(end) is not int:
        raise TaskTraceArgumentError("source_start_char and source_end_char must be provided together as integers")
    if not 0 <= start <= end <= len(text):
        raise TaskTraceArgumentError(
            f"source range [{start},{end}) is outside complete_chars={len(text)}; no source text returned"
        )
    out.update(source_start_char=start, source_end_char=end, text=text[start:end])
    return out


def _read_call(ctx: Any, record: Mapping[str, Any], root: Path, task_id: str, call_id: str,
               digest: str, start: Any, end: Any, plane: str, status_root: Path) -> Dict[str, Any]:
    if not call_id or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise TaskTraceArgumentError("read_call requires call_id and a lowercase 64-character manifest_sha256")
    if re.fullmatch(r"tool_dispatch_[0-9a-f]{32}", call_id):
        from ouroboros.observability import call_manifest_path

        root = status_root  # dispatch input is persisted in the canonical/native task plane
        published = {"class": "tool_dispatch", "ref": {
            "path": str(call_manifest_path(root, task_id, call_id)),
            "call_id": call_id, "sha256": digest,
        }}
        call_types = _DISPATCH_CALL_TYPES
    else:
        published = _find_manifest(record, call_id, digest, call_class="tool")
        call_types = _TOOL_CALL_TYPES
    raw, manifest = _projection_bytes(ctx, root, task_id, published, call_types=call_types)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileNotFoundError("redacted call projection is not UTF-8 source") from exc
    source = _range_projection(text, start=start, end=end, source={
        "kind": ("redacted_dispatch_projection" if published["class"] == "tool_dispatch"
                 else "redacted_call_projection"),
        "task_id": task_id, "call_id": call_id,
        "manifest_sha256": digest, "call_type": str(manifest.get("call_type") or published["class"]),
        "plane": plane, "raw_payload_used": False, "retention": "digest_pinned_manifest_and_cas",
    })
    return {"task_id": task_id, "operation": "read_call", "source": source}


_PRIVATE_REASONING_KEYS = frozenset({
    "reasoning", "reasoning_content", "reasoning_details", "thinking",
    "nativeContinuation", "_anthropic_native_content", "_anthropic_consumed_receipts",
    "_anthropic_native_opaque", "_anthropic_native_custody",
})
_PRIVATE_REASONING_BLOCKS = frozenset({"thinking", "reasoning", "redacted_thinking"})


def _is_private_reasoning_block(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    block_type = str(value.get("type") or "").strip().lower()
    return (value.get("thought") is True or block_type in _PRIVATE_REASONING_BLOCKS
            or block_type.startswith("reasoning."))


def _public_authored_value(value: Any) -> Any:
    """The public assistant-authored projection, never provider reasoning.

    The immutable source is still the published redacted CAS object.  This
    projection deliberately selects its ``message`` and drops usage plus every
    provider-private reasoning carrier before source hashing/ranging.
    """
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name in _PRIVATE_REASONING_KEYS or name == "response_id":
                continue
            if name == "signature":
                continue
            if name == "content" and isinstance(item, list):
                out[name] = [
                    _public_authored_value(block)
                    for block in item
                    if not _is_private_reasoning_block(block)
                ]
            else:
                out[name] = _public_authored_value(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_public_authored_value(item) for item in value if not _is_private_reasoning_block(item)]
    return value


def _authored_projection_text(raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FileNotFoundError("redacted authored projection is not valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or "message" not in payload:
        raise FileNotFoundError("retained LLM response has no public authored message projection")
    message = _public_authored_value(payload["message"])
    if isinstance(message, str):
        return message
    return _canonical(message).decode("utf-8")


def _read_authored(ctx: Any, record: Mapping[str, Any], root: Path, task_id: str, output_id: str,
                   start: Any, end: Any, plane: str, presence_scope: str) -> Dict[str, Any]:
    if output_id == "authoritative_result":
        if not _has_authoritative_result(record):
            raise FileNotFoundError("physical task has no settled authoritative result")
        text = str(record.get("result") or "")
        source = _range_projection(text, start=start, end=end, source={
            "kind": "authoritative_result", "task_id": task_id, "selected": True,
            "terminal_origin": str(record.get("terminal_origin") or "unknown"), "plane": plane,
            "retention": "current_physical_task_result",
            "immutable": False,
            "current_reread": {"tool": "query_records", "arguments": _trace_arguments(
                task_id, "read_authored_output", presence_scope,
                authored_output_id="authoritative_result",
            )},
        })
        return {"task_id": task_id, "operation": "read_authored_output", "source": source}
    found = next((row for row in _authored_rows(record, task_id, presence_scope)
                  if row.get("authored_output_id") == output_id and not row.get("selected")), None)
    if found is None:
        raise FileNotFoundError("authored_output_id is not published by this physical task")
    digest = str(found.get("manifest_sha256") or "")
    call_id = output_id.split(":", 2)[1] if output_id.startswith("response:") else ""
    published = _find_manifest(record, call_id, digest, call_class="llm_response")
    raw, manifest = _projection_bytes(
        ctx, root, task_id, published, call_types=_AUTHORED_CALL_TYPES,
    )
    text = _authored_projection_text(raw)
    source = _range_projection(text, start=start, end=end, source={
        "kind": "observed_authored_output", "task_id": task_id,
        "authored_output_id": output_id, "selected": False,
        "selection_basis": "observed_llm_response", "call_id": call_id,
        "manifest_sha256": digest, "call_type": str(manifest.get("call_type") or "llm_response"),
        "plane": plane, "raw_payload_used": False,
        "projection": "public_authored_message_without_provider_reasoning",
        "retention": "derived_from_digest_pinned_redacted_manifest_and_cas",
    })
    return {"task_id": task_id, "operation": "read_authored_output", "source": source}


def query_task_trace(
    ctx: Any, *, task_id: str, operation: str = "list", stream: str = "",
    cursor: Any = None, limit: int = 50, call_id: str = "", manifest_sha256: str = "",
    authored_output_id: str = "", source_start_char: Any = None, source_end_char: Any = None,
    presence_scope: str = "",
) -> Dict[str, Any]:
    """Return one internal task-trace projection for ``query_records``."""
    task_id = validate_task_id(task_id)
    if operation not in TRACE_OPERATIONS:
        raise TaskTraceArgumentError(f"task_trace operation must be one of {', '.join(TRACE_OPERATIONS)}")
    if type(limit) is not int or not 1 <= limit <= 200:
        raise TaskTraceArgumentError("task_trace limit must be an integer from 1 to 200")
    root, plane = _status_root(ctx)
    _admit_authorization_sources(ctx, root, task_id)
    _authorize(ctx, root, task_id, presence_scope)
    roots = _roots(ctx, root, task_id, native=plane == "native_pin")
    record, record_root = _physical_record(ctx, roots, task_id)

    if operation == "list":
        if stream not in TRACE_STREAMS:
            raise TaskTraceArgumentError(f"task_trace list requires stream={('|'.join(TRACE_STREAMS))}")
        if any(value not in ("", None) for value in (call_id, manifest_sha256, authored_output_id,
                                                       source_start_char, source_end_char)):
            raise TaskTraceArgumentError("call/output/source-range parameters do not belong to task_trace operation=list")
        if stream == "authored_outputs":
            return _list_authored(record, task_id, cursor, limit, plane, presence_scope)
        return _list_logs(
            ctx, record, roots, task_id, stream, cursor, limit, plane, presence_scope,
        )
    if cursor is not None or stream:
        raise TaskTraceArgumentError("stream/cursor belong only to task_trace operation=list")
    if operation == "read_call":
        if authored_output_id:
            raise TaskTraceArgumentError("authored_output_id belongs only to operation=read_authored_output")
        return _read_call(ctx, record, record_root, task_id, call_id, manifest_sha256,
                          source_start_char, source_end_char, plane, root)
    if call_id or manifest_sha256:
        raise TaskTraceArgumentError("call_id/manifest_sha256 belong only to operation=read_call")
    if not authored_output_id:
        raise TaskTraceArgumentError("read_authored_output requires authored_output_id")
    return _read_authored(ctx, record, record_root, task_id, authored_output_id,
                          source_start_char, source_end_char, plane, presence_scope)


__all__ = ["TRACE_OPERATIONS", "TRACE_STREAMS", "TaskTraceArgumentError", "query_task_trace"]
