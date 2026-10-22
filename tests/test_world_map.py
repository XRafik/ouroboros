"""My map of my world (`memory/WORLD.md`): the host refreshes only its measured block, the
mind publishes the rest through ``update_world`` on the canonical root, and the context
presents the file as mine, not as a disposable profile."""
from __future__ import annotations

import json
import pathlib

from ouroboros import world_profiler as wprof


def _measured(stamp: str) -> str:
    return (f"{wprof.MEASURED_START}\n## System (measured at startup, {stamp})\n"
            f"- **OS**: test\n{wprof.MEASURED_END}")


def _fake_measured(monkeypatch, stamp: str) -> None:
    monkeypatch.setattr(wprof, "measured_block", lambda repo_dir="", data_dir="": _measured(stamp))


def test_refresh_replaces_only_the_measured_block_and_keeps_my_text(tmp_path, monkeypatch):
    _fake_measured(monkeypatch, "second")
    path = tmp_path / "WORLD.md"
    mine = "## What lives here\n- a Claude Code chat named X, inbox /tmp/cc-socks/1.sock (seen 2026-10-22)\n"
    path.write_text(f"{wprof.TITLE}\n\nintro\n\n{_measured('first')}\n\n{mine}", encoding="utf-8")

    assert wprof.refresh_world_profile(str(path)) is True
    text = path.read_text(encoding="utf-8")
    assert "measured at startup, second" in text and "first" not in text
    assert mine in text and text.count(wprof.MEASURED_START) == 1
    # Idempotent: an unchanged block writes nothing.
    assert wprof.refresh_world_profile(str(path)) is False


def test_refresh_fences_a_legacy_first_boot_profile_once_and_keeps_later_notes(tmp_path, monkeypatch):
    _fake_measured(monkeypatch, "now")
    path = tmp_path / "WORLD.md"
    path.write_text(
        "# WORLD.md — Environment Profile\n\nThis is where I currently exist.\n\n## System\n- **OS**: old\n\n"
        "## Available Tools\n`git`\n\n## File System Rules\n- `/r` contains my codebase.\n\n"
        "*(Generated automatically on first boot)*\n\n## My notes\n- kept\n", encoding="utf-8")

    assert wprof.refresh_world_profile(str(path)) is True
    text = path.read_text(encoding="utf-8")
    assert text.startswith(wprof.TITLE) and text.count(wprof.MEASURED_START) == 1
    assert "- **OS**: old" not in text and "Generated automatically" not in text
    assert "## My notes\n- kept" in text
    assert wprof.refresh_world_profile(str(path)) is False


def test_refresh_keeps_unrecognized_text_whole_and_tolerates_crlf(tmp_path, monkeypatch):
    _fake_measured(monkeypatch, "now")
    path = tmp_path / "WORLD.md"
    path.write_bytes(b"# Mine\r\n\r\n- note one\r\n- note two\r\n")

    assert wprof.refresh_world_profile(str(path)) is True
    text = path.read_bytes().decode("utf-8")
    assert text.startswith("# Mine") and wprof.MEASURED_START in text
    assert "- note one\r\n- note two\r\n" in text

    # A fenced block whose inside carries CRLF is still one block.
    path.write_bytes(b"# Mine\r\n\r\n" + _measured("old").replace("\n", "\r\n").encode() + b"\r\n\r\n- note\r\n")
    assert wprof.refresh_world_profile(str(path)) is True
    text = path.read_bytes().decode("utf-8")
    assert text.count(wprof.MEASURED_START) == 1 and "old" not in text and "- note\r\n" in text


def test_refresh_generates_a_missing_file_with_an_empty_map(tmp_path, monkeypatch):
    _fake_measured(monkeypatch, "now")
    path = tmp_path / "WORLD.md"
    assert wprof.refresh_world_profile(str(path)) is True
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# WORLD.md") and "## What lives here" in text and wprof.MEASURED_END in text


def test_generate_names_the_roots_and_calls_the_probe_a_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(wprof, "_tools_found", lambda: ["git", "python3"])
    monkeypatch.setattr(wprof, "get_cpu_info", lambda: "test-cpu")
    monkeypatch.setattr(wprof, "get_system_memory", lambda: "1.0 GB")
    out = tmp_path / "WORLD.md"
    wprof.generate_world_profile(str(out), "/repo root", "/data root")
    text = out.read_text(encoding="utf-8")
    assert "`/repo root` contains my codebase" in text and "`/data root` contains my memory" in text
    assert "A probe of common binaries, not a census" in text and "`git, python3`" in text
    assert text.index(wprof.MEASURED_START) < text.index("## What lives here")


def test_with_measured_block_keeps_the_hosts_block_whatever_the_mind_sends():
    old = f"{wprof.TITLE}\n\n{_measured('host')}\n\n## What lives here\n- old note\n"
    # The mind dropped the fence: the host's block comes back after the title.
    rendered = wprof.with_measured_block(f"{wprof.TITLE}\n\n## What lives here\n- new note\n", old)
    assert rendered.startswith(wprof.TITLE) and "measured at startup, host" in rendered and "- new note" in rendered
    # The mind edited inside the fence: the host's block wins.
    rendered = wprof.with_measured_block(f"{wprof.TITLE}\n\n{_measured('forged')}\n\n- new note\n", old)
    assert "forged" not in rendered and "measured at startup, host" in rendered and rendered.count(wprof.MEASURED_START) == 1


def test_context_presents_the_map_as_mine(tmp_path):
    from ouroboros.context import build_memory_sections
    from ouroboros.memory import Memory

    (tmp_path / "memory").mkdir(parents=True)
    (tmp_path / "memory" / "WORLD.md").write_text("world-map-data", encoding="utf-8")
    combined = "\n\n".join(build_memory_sections(Memory(drive_root=tmp_path)))
    assert "world-map-data" in combined
    assert "update_world" in combined and "delete WORLD.md" not in combined


def test_delegate_start_discloses_that_a_run_sees_no_owner_sessions():
    from ouroboros.tools.delegate import get_tools

    schema = next(entry.schema for entry in get_tools() if entry.name == "delegate_start")
    assert "engine-scoped native state" in schema["description"] and "no courier" in schema["description"]


def test_write_tools_redirect_the_map_to_update_world():
    from ouroboros.tool_access import light_cognitive_or_root_redirect

    message = light_cognitive_or_root_redirect("edit_text", {"root": "runtime_data", "path": "memory/WORLD.md"})
    assert message and "update_world" in message
    assert light_cognitive_or_root_redirect("edit_text", {"root": "runtime_data", "path": "memory/notes.md"}) is None


def _world_ctx(canonical: pathlib.Path, drive: pathlib.Path):
    from ouroboros.tools.registry import ToolContext

    # A forked execution drive with the canonical budget root: the shape of a child task.
    return ToolContext(repo_dir=canonical / "repo", drive_root=drive, task_id="t1", current_chat_id=444,
                       task_metadata={"budget_drive_root": str(canonical)})


def test_update_world_publishes_on_the_canonical_root_with_revision_and_the_hosts_block(tmp_path, monkeypatch):
    from ouroboros.tools.control_runtime import _update_world

    canonical, drive = tmp_path / "canonical", tmp_path / "fork"
    (canonical / "memory").mkdir(parents=True)
    (drive / "memory").mkdir(parents=True)
    world = canonical / "memory" / "WORLD.md"
    world.write_text(f"{wprof.TITLE}\n\n{_measured('host')}\n\n## What lives here\n- old\n", encoding="utf-8")
    ctx = _world_ctx(canonical, drive)

    # An existing map needs its revision; a stale one is refused with the current revision.
    refused = _update_world(ctx, "# WORLD.md\n\n## What lives here\n- new\n")
    assert "revision_required" in refused
    import hashlib
    revision = hashlib.sha256(world.read_bytes()).hexdigest()
    stale = _update_world(ctx, "# WORLD.md\n\n## What lives here\n- new\n", expected_revision="0" * 64)
    assert "revision_conflict" in stale and revision in stale

    result = _update_world(ctx, "# WORLD.md\n\n## What lives here\n- new\n", expected_revision=revision)
    assert result.startswith("OK: world map updated") and "revision=" in result
    text = world.read_text(encoding="utf-8")
    assert "- new" in text and "- old" not in text and "measured at startup, host" in text
    # The forked drive stayed untouched: the map lives on the canonical root the context reads.
    assert not (drive / "memory" / "WORLD.md").exists()
    rows = [json.loads(line) for line in (canonical / "memory" / "world_journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and rows[-1]["new_content"] == text and rows[-1]["task_id"] == "t1"


def test_update_world_warns_above_the_context_budget_without_refusing(tmp_path):
    from ouroboros.tools.control_runtime import _update_world

    canonical = tmp_path / "canonical"
    (canonical / "memory").mkdir(parents=True)
    ctx = _world_ctx(canonical, canonical)
    big = f"{wprof.TITLE}\n\n{_measured('host')}\n\n" + "x" * (wprof.WORLD_SECTION_BUDGET_CHARS + 10)
    result = _update_world(ctx, big)
    assert result.startswith("OK:") and "WORLD_SIZE_NOTICE" in result
    assert _update_world(ctx, "   ").startswith("⚠️ REJECTED")
