"""Guard of DEVELOPMENT 06 "Cache-friendliness invariant": an ordinary round appends.

An installed extension publishes a changing ``context_snapshot`` every round while
roster, owner words, review facts and completion controls also arrive. The scripted
model is the only transport replacement; ``run_llm_loop``, tools and extension
admission are real. The oracle compares the sent requests themselves, so no
``sanction_rewrite`` label can make an ordinary rewrite pass: #2076 relabelled the
older seam test and the rule, and every changed snapshot then made OpenAI-family
providers re-read the whole conversation (measured 2026-10-21: 99.5 % -> 62.7 % of
input read from cache on 95 comparable sends).
"""
import copy
import json

import pytest

from ouroboros import extension_loader, loop, skill_context_snapshot, transcript_prefix
from ouroboros.context_budget import HOST_CONTEXT_KIND_KEY, bound_host_row
from ouroboros.skill_loader import (
    SkillReviewState, load_skill, save_enabled, save_review_state,
    save_skill_grants, skill_state_dir_path,
)
from tests.test_transcript_prefix import ANSWER, _four_tool_rounds, _prefix_breaks, full_loop, select_completion

_ = full_loop  # the fixture is imported for pytest


@pytest.fixture
def installed_publisher(full_loop):
    f = full_loop
    payload = f.ctx.repo_dir / "cycle-feed"
    payload.mkdir()
    manifest = {"name": "cycle-feed", "version": "1", "description": "Cycle prefix fixture",
                "type": "extension", "entry": "plugin.py", "plugin_api": "2.0",
                "permissions": ["context_snapshot"], "context_snapshot": {"path": "snapshot.json"}}
    (payload / "SKILL.md").write_text(json.dumps(manifest))
    (payload / "plugin.py").write_text("def register(api):\n    pass\n")
    root = f.ctx.drive_root
    skill = load_skill(payload, root)
    save_enabled(root, skill.name, True)
    save_review_state(root, skill.name, SkillReviewState(status="clean", content_hash=skill.content_hash))
    save_skill_grants(root, skill.name, [], content_hash=skill.content_hash, requested_keys=[],
                      granted_permissions=["context_snapshot"], requested_permissions=["context_snapshot"])
    skill = load_skill(payload, root)
    assert extension_loader.load_extension(skill, lambda: {}, drive_root=root,
                                           skills=[skill], _force_in_process=True) is None
    path = skill_state_dir_path(root, skill.name) / "snapshot.json"

    def publish(version):
        # Fixed dates remove sleeps, expiry and wall-clock renewal from the test.
        path.write_text(json.dumps({"schema_version": 1, "observed_at": "2000-01-01T00:00:00Z",
                                   "valid_until": "2999-01-01T00:00:00Z", "text": f"Quota sample {version}"}))
        (root / "state" / "queue_snapshot.json").write_text(json.dumps({
            "ts": "2026-10-21T10:00:00Z", "running": [{"id": "peer-root", "task": {
                "id": "peer-root", "title": f"Peer work {version}", "chat_id": 0}}],
            "pending": [], "worker_total": 1,
        }))
    publish(0)
    try:
        yield f, publish
    finally:
        extension_loader.unload_extension(skill.name)


def _block_view(block):
    return {key: item for key, item in block.items() if key != "cache_control"} if isinstance(block, dict) else block


def message_view(message):
    """Drop only host custody keys and cache placement; keep public bytes and block order."""
    clean = {key: item for key, item in message.items() if key != "cache_control" and not str(key).startswith("_")}
    content = clean.get("content")
    if isinstance(content, list):
        content = [_block_view(block) for block in content]
        # Cache placement wraps a plain string in one text block on some routes.
        if len(content) == 1 and isinstance(content[0], dict) and set(content[0]) == {"type", "text"}:
            content = content[0]["text"]
        clean["content"] = content
    return clean


def tools_view(schemas):
    return [_block_view(schema) for schema in schemas or []]


def _ordinary_rewrites(sends):
    failures = []
    for step, (previous, current) in enumerate(zip(sends, sends[1:]), start=2):
        previous, current = [message_view(m) for m in previous], [message_view(m) for m in current]
        if len(current) < len(previous):
            failures.append((step, "shrunk", len(previous), len(current)))
        for index, (before, after) in enumerate(zip(previous, current)):
            if before != after:
                failures.append((step, index, before.get("content"), after.get("content")))
                break
    return failures


def _address_previous_snapshot(original):
    """The #2076 behaviour: replace the previous full snapshot with a pointer and sanction it."""
    def append(ctx, messages, drive_root):
        changed = original(ctx, messages, drive_root)
        rows = [i for i, m in enumerate(messages)
                if m.get(HOST_CONTEXT_KIND_KEY) == skill_context_snapshot.SNAPSHOT_KIND]
        if changed and len(rows) > 1 and "Superseded" not in str(messages[rows[-2]].get("content")):
            messages[rows[-2]] = bound_host_row(skill_context_snapshot.SNAPSHOT_KIND, "[Superseded skill snapshot]")
            transcript_prefix.sanction_rewrite(ctx, "superseded_skill_snapshot")
        return changed
    return append


@pytest.mark.parametrize("variant", ["unchanged_snapshot", "changing_snapshot", "sanctioned_rewrite"])
def test_an_ordinary_cycle_appends_whatever_a_seam_calls_its_rewrite(installed_publisher, monkeypatch, variant):
    f, publish = installed_publisher
    model = _four_tool_rounds(f)
    schemas, wires = [], []
    if variant == "sanctioned_rewrite":
        monkeypatch.setattr(skill_context_snapshot, "maybe_append_skill_snapshots",
                            _address_previous_snapshot(skill_context_snapshot.maybe_append_skill_snapshots))

    def scripted(*args, **kwargs):
        from ouroboros.llm_attempt import _physical_candidate
        from ouroboros.llm_claudexor import _request

        schemas.append(copy.deepcopy(args[3]))
        wires.append((
            _physical_candidate({"messages": args[1], "tools": args[3]}),
            _request({"source": "codex", "resolved_model": "fixture"}, args[1], args[3],
                     {"model_account_override": "", "_no_account_preference": True}),
        ))
        if f.model_step >= 4:
            f.model_inputs.append(copy.deepcopy(args[1]))
            f.model_step += 1
            assert f.model_step < 9, f.progress
            # New owner words can invalidate the retained selection: select afresh.
            result = select_completion(f, answer=ANSWER), 0.0
        else:
            result = model(*args, **kwargs)
        publish(0 if variant == "unchanged_snapshot" else f.model_step)
        if 2 <= f.model_step < 4:
            f.run_args["incoming_messages"].put(f"Owner follow-up {f.model_step}: keep the complete budget.")
        return result

    monkeypatch.setattr(loop, "call_llm_with_retry", scripted)
    result, usage, _trace = f.run()
    assert result == ANSWER, (result, f.progress)
    assert len(f.model_inputs) >= 5
    failures = _ordinary_rewrites(f.model_inputs)
    if variant == "sanctioned_rewrite":
        # The label explains the rewrite; it neither hides it from the oracle nor from the counts.
        assert failures, "a sanctioned ordinary rewrite must still fail the append-only oracle"
        assert usage["prompt_prefix_breaks"] >= 1
        assert {b["sanctioned_by"] for b in _prefix_breaks(f.events)} == {"superseded_skill_snapshot"}
        record = json.loads(transcript_prefix.history_changes_path(f.ctx.drive_root).read_text())
        assert record["origins"]["superseded_skill_snapshot"]["count"] == usage["prompt_prefix_breaks"]
        return
    assert not failures, {"rewrites": failures, "breaks": _prefix_breaks(f.events)}
    for step in range(1, len(schemas)):
        assert tools_view(schemas[step]) == tools_view(schemas[step - 1]), "tool schemas changed"
    for route in range(2):
        requests = [pair[route] for pair in wires]
        for previous, current in zip(requests, requests[1:]):
            size = len(previous["messages"])
            assert [message_view(m) for m in current["messages"][:size]] == [message_view(m) for m in previous["messages"]], (
                route, "wire prefix changed")
            assert tools_view(current.get("tools")) == tools_view(previous.get("tools")), (route, "wire tools changed")
    assert _prefix_breaks(f.events) == []
    assert "prompt_prefix_breaks" not in usage
    final = json.dumps(f.model_inputs[-1])
    for marker in ("[CONTEXT_FACTS]", "[ACCEPTANCE_SUBJECT_OBSERVATION]",
                   "[DELIVERY_FINALIZATION_CONTROL]", "[INDEPENDENT_ROOTS]", "Owner follow-up"):
        assert marker in final, marker
    snapshots = [m for m in f.model_inputs[-1] if m.get(HOST_CONTEXT_KIND_KEY) == skill_context_snapshot.SNAPSHOT_KIND]
    assert len(snapshots) >= 5 if variant == "changing_snapshot" else len(snapshots) == 1
