"""Place membership and view composition over the real indexed history."""
from types import SimpleNamespace

import pytest

from ouroboros import chat_chain, memory_inventory as mi, memory_view as mv
from ouroboros.dialogue_provenance import row_provenance
from tests import _memory_inventory_shared as shared


def _focus(room=444):
    return {"id": "focus1", "chat_id": 1, "metadata": {
        "usage_category": "consciousness", "wake_cause": "focus",
        "focus": {"room_chat_id": room, "place_id": "garden", "conversation_key": "garden:talk"}}}


@pytest.mark.parametrize("stamp", [
    {"presence": {"binding_id": "old"}}, {"presence_provenance": {"place_id": "garden"}},
    {"source": "presence:telegram"}, {"type": "presence_delivery"},
])
def test_place_predicate_is_typed_and_inventory_retains_it(stamp):
    row = shared.msg("2026-09-05", "presence:telegram", chat_id=444, **stamp)
    assert row_provenance(row) == row_provenance(mi.row_meta(row)) == "place"
    assert row_provenance({"text": "presence:telegram", "transport": {"provider": "telegram"}}) == "other"


def test_many_places_keep_their_rows_and_main_keeps_owner_rows(tmp_path):
    from ouroboros.gateway.history_paging import room_lens

    shared.world(tmp_path)
    rows = [shared.msg("2026-09-05", f"PLACE_WORDS_{room}", chat_id=room,
                       presence_provenance={"place_id": f"p{room}", "conversation_key": f"c{room}"})
            for room in range(400, 600)]
    rows += [shared.msg("2026-09-05", f"OWNER_WORDS_{n}") for n in range(50)]
    shared.append(tmp_path / "logs/chat.jsonl", *rows)
    before = list(chat_chain.iter_rows(tmp_path))
    grouped = mi.open_rows_by_room(tmp_path)
    assert len(grouped["1"]) >= 50
    assert not any(row_provenance(meta) == "place" for _a, meta, _p in grouped["1"])
    main_history = list(chat_chain.iter_room_rows(tmp_path, "1"))
    assert not any(row_provenance(row) == "place" for _a, row, _p in main_history)
    assert sum(row["text"].startswith("OWNER_WORDS_") for _a, row, _p in main_history) == 50
    for room in range(400, 600):
        lens = room_lens(tmp_path, room, set(), [], {})
        assert lens["chat"].keys == lens["progress"].keys == (("chat_id", room),)
        indexed = list(chat_chain.iter_room_rows(tmp_path, str(room)))
        assert len(indexed) == len(grouped[str(room)]) == 1
        assert indexed[0][0] == grouped[str(room)][0][0]
    assert before == list(chat_chain.iter_rows(tmp_path))  # presentation never rewrites history


def test_focus_uses_own_room_before_category_and_own_wake_sees_only_index(tmp_path):
    shared.world(tmp_path)
    stamp = {"place_id": "garden", "conversation_key": "garden:talk", "source_event_id": "event1"}
    shared.append(tmp_path / "logs/chat.jsonl",
                  shared.msg("2026-09-05", "PRIVATE_PLACE_WORDS", chat_id=444, presence_provenance=stamp),
                  shared.msg("2026-09-06", "PRIVATE_PLACE_ANSWER", chat_id=444, direction="out",
                             type="presence_delivery", transport={"delivery": {
                                 "state": "delivered", "presence_provenance": stamp}}))
    focus = _focus()
    own = {"id": "wake1", "metadata": {"usage_category": "consciousness", "wake_cause": "own_clock"}}
    spec = mv.view_spec_for_task(focus, tmp_path)
    assert (spec.role, spec.room_id, spec.marks, spec.live_rooms) == ("presence", "444", "room_and_global", "none")
    assert mv.view_role(own) == "consciousness"
    focused = mv.capture_memory_view(tmp_path, focus, spec)
    wake = mv.capture_memory_view(tmp_path, own, mv.view_spec_for_task(own, tmp_path))
    own_text, focus_text = mv.render_room(wake), mv.render_room(focused)
    assert next(room for room in wake.live_rooms if room["room_id"] == "444")["words"] == []
    assert "PRIVATE_PLACE_WORDS" in focus_text and "PRIVATE_PLACE_ANSWER" in focus_text
    assert "PRIVATE_PLACE_WORDS" not in own_text and "PRIVATE_PLACE_ANSWER" not in own_text
    assert "Place garden; conversation garden:talk; answered events 1" in own_text
    assert "memory_read(room_id='444', rows=true)" in own_text
    assert mv.render_story(wake) == mv.render_story(focused)


def test_own_wake_keeps_place_notes_by_address_even_after_all_rows_are_sealed(tmp_path):
    from ouroboros.chronicle_store import ChronicleStore
    from ouroboros.knowledge import focus_signature

    shared.world(tmp_path)
    task = _focus()
    author = focus_signature(SimpleNamespace(task_id=task["id"], current_chat_id=444, task_metadata=task["metadata"]))
    ChronicleStore(tmp_path).write_note(room_id="444", task_id=task["id"], text="PRIVATE_PLACE_NOTE", author=author)
    own = {"metadata": {"usage_category": "consciousness", "wake_cause": "own_clock"}}
    wake = mv.capture_memory_view(tmp_path, own, mv.view_spec_for_task(own, tmp_path))
    focused = mv.capture_memory_view(tmp_path, task, mv.view_spec_for_task(task, tmp_path))
    assert "PRIVATE_PLACE_NOTE" not in mv.render_room(wake)
    assert "memory_read(node_id=" in mv.render_room(wake)
    assert "PRIVATE_PLACE_NOTE" in mv.render_room(focused)


def test_wake_never_repeats_main_words_in_live_rooms(tmp_path):
    shared.world(tmp_path)
    shared.append(tmp_path / "logs/chat.jsonl", shared.msg("2026-09-05", "SHARED_TRANSPORT_WORDS", chat_id=777))
    task = {"metadata": {"usage_category": "consciousness"}}
    snapshot = mv.capture_memory_view(tmp_path, task, mv.view_spec_for_task(task, tmp_path))
    rendered = mv.render_room(snapshot)
    assert rendered.count("SHARED_TRANSPORT_WORDS") == 1
    assert "alpha again" in rendered  # non-place room's independent words still appear


def test_shared_prefix_is_identical_and_focus_assignment_is_volatile(tmp_path, monkeypatch):
    from tests import _memory_view_context as context
    import ouroboros.presence_context as presence_context

    monkeypatch.setattr(presence_context, "build_presence_context_section", lambda *args, **kw: "FOCUS_ASSIGNMENT")
    env, memory, _rooms = context.world(tmp_path)
    own = {"id": "wake1", "metadata": {"usage_category": "consciousness", "wake_cause": "own_clock"}}
    a, b, _c, _cap = context.blocks(env, memory, own)
    focus = _focus()
    focus["metadata"]["presence"] = {"binding_id": "garden"}
    fa, fb, fc, _cap = context.blocks(env, memory, focus)
    assert (a, b) == (fa, fb)
    assert "FOCUS_ASSIGNMENT" in fc and "FOCUS_ASSIGNMENT" not in fa + fb


def test_memory_author_keeps_originating_focus_room():
    from ouroboros.knowledge import focus_signature

    task = _focus()
    author = focus_signature(SimpleNamespace(task_id=task["id"], current_chat_id=1, task_metadata=task["metadata"]))
    assert author["focus"]["role"] == "presence"
    assert {k: author["focus"][k] for k in ("room_id", "place_id", "conversation_key")} == {
        "room_id": "444", "place_id": "garden", "conversation_key": "garden:talk"}
