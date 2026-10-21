import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ouroboros import places as p
from ouroboros.presence_bindings import PresenceBinding, PresenceEndpoint, save_presence_binding


def connect(root, **kw):
    return p.connect_place(root, connector="slack-bridge", provider="slack", account_id="team", **kw)


def test_store_choices_revision_and_refresh(tmp_path):
    place = connect(tmp_path, wakes=[p.FACT_MENTION])
    changed = p.edit_place(tmp_path, place.place_id, "add_note", author=p.AUTHOR_OWNER, text="Owner words\nverbatim.")
    changed = p.edit_place(tmp_path, place.place_id, "set_state", author=p.AUTHOR_OUROBOROS, state="silent")
    again = connect(tmp_path, wakes=[p.FACT_ANY_MESSAGE], label="Updated connector")
    assert again.notes == changed.notes and again.wakes == place.wakes and again.state == "silent"
    assert p.get_place(tmp_path, place.place_id) == again
    with pytest.raises(p.PlaceError, match="Current revision"):
        p.edit_place(tmp_path, place.place_id, "set_model", author="owner", model="x", expected_revision=1)
    final = p.edit_place(tmp_path, place.place_id, "set_model", author="owner", model="x", expected_revision=again.revision)
    assert final.model == "x"


def test_facts_and_empty_wakes(tmp_path):
    place = connect(tmp_path, wakes=[p.FACT_MENTION])
    assert p.wake_matches(place, [p.FACT_MENTION])
    assert not p.wake_matches(place, ["please mention me"])
    assert not p.wake_matches(place, [p.FACT_MENTION, p.FACT_FROM_BOT])
    assert p.wake_matches(replace(place, wakes=place.wakes + (p.WakeItem(p.FACT_FROM_BOT, "owner"),)),
                          [p.FACT_MENTION, p.FACT_FROM_BOT])
    assert not p.wake_matches(replace(place, wakes=()), [p.FACT_LEGACY_ADDRESSED])


def test_resolution_and_owner_confirmation(tmp_path):
    broad = connect(tmp_path)
    narrow = connect(tmp_path, conversation_id="room", scope="conversation")
    assert p.resolve_place(tmp_path, connector="slack-bridge", provider="slack", account_id="team", conversation_id="room") == narrow
    assert p.resolve_place(tmp_path, connector="slack-bridge", provider="slack", account_id="team", conversation_id="other") == broad
    assert p.resolve_place(tmp_path, connector="other", binding_id=narrow.place_id) is None
    with pytest.raises(p.PlaceError, match="owner's door"):
        p.edit_place(tmp_path, narrow.place_id, "confirm_owner_account", author="ouroboros", platform_actor_id="anton")
    confirmed = p.edit_place(tmp_path, narrow.place_id, "confirm_owner_account", author="owner", platform_actor_id="anton")
    assert p.is_owner_account(confirmed, "anton", "team")
    assert not p.is_owner_account(confirmed, "anton", "other")
    assert not p.is_owner_account(confirmed, "stranger", "team")


def test_migration_exact_sources_and_idempotence(tmp_path, monkeypatch):
    root = tmp_path
    behavior = SimpleNamespace(skill_dir=root, manifest=SimpleNamespace(raw_extra={"presence": {
        "instructions": "Keep these exact words.\n", "context_topics": ["social"],
        "runtime_defaults": {"model_slot": "main"}}}))
    connector = SimpleNamespace(manifest=SimpleNamespace(contributes=[{"provides": "place", "wakes": ["group_dm"]}]))
    monkeypatch.setattr("ouroboros.skill_loader.find_skill", lambda _root, name: behavior if name == "mind" else connector)
    state = root / "state" / "skills" / "mind" / "presence_profile_state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"runtime_overrides": {"model_slot": "light"}, "workspace_root": "/work"}))
    binding = PresenceBinding("a" * 32, "slack-bridge", "mind", PresenceEndpoint("slack", "team", "*"),
                              PresenceEndpoint("slack", "team", "elsewhere"), False)
    save_presence_binding(root, binding)
    source = (root / "state" / "presence_bindings.json").read_bytes()
    place, = p.load_places(root)
    assert place.state == "paused" and place.legacy_binding_ids == (binding.binding_id,)
    assert place.notes[0] == p.NoteEntry("Keep these exact words.\n", "migration")
    assert place.context_topics == ("social",) and place.working_folder == "/work" and place.model == "light"
    assert place.destination["conversation_id"] == "elsewhere"
    assert {w.fact for w in place.wakes} == {"legacy_addressed", "group_dm"}
    saved = p.edit_place(root, place.place_id, "set_state", author="owner", state="silent")
    assert p.load_places(root) == [saved]
    assert (root / "state" / "presence_bindings.json").read_bytes() == source


def test_empty_and_malformed_sources_preserved(tmp_path):
    assert p.load_places(tmp_path) == []
    assert p.load_places(tmp_path) == []
    other = tmp_path / "broken"
    path = other / "state" / "presence_bindings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken")
    with pytest.raises(p.PlaceError, match="repair"):
        p.load_places(other)
    assert path.read_text() == "{broken"
    assert not p.places_path(other).exists()
    path.unlink()
    assert p.load_places(other) == []


def test_chat_identity_matches_old_runner():
    from ouroboros.presence_runner import _stable_numeric_id
    assert p.conversation_chat_id("slack:team:room:0") == _stable_numeric_id("presence-conversation", "slack:team:room:0")
