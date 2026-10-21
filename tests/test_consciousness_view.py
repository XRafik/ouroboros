"""Facts use typed place/index seams and keep missing evidence distinct from zero."""

import pathlib

from ouroboros import consciousness_view as view, places
from ouroboros.consciousness_wake import PLACEHOLDERS, render_wake_message


def test_places_context_has_every_place_and_room_without_reading_history(monkeypatch, tmp_path):
    configured = [places.Place("mail", "inbox", "mail", label="Inbox"),
                  places.Place("quiet", "chat", "chat", label="Quiet room", state="silent"),
                  places.Place("paused", "chat", "chat", label="Paused room", state="paused")]
    monkeypatch.setattr(places, "load_places", lambda root: configured)
    calls = []
    def rooms(root, place_id):
        calls.append((root, place_id))
        return {"mail": [{"room_chat_id": -1, "unanswered_count": 2},
                          {"room_chat_id": -2, "unanswered_count": 1}], "quiet": [],
                "paused": [{"room_chat_id": -3, "unanswered_count": None}]}[place_id]
    monkeypatch.setattr(places, "place_room_index", rooms, raising=False)
    rows = view.place_views(tmp_path)
    assert [row["unanswered"] for row in rows] == [3, 0, None]
    text = view.places_text(rows)
    assert "Inbox [mail]: active; unanswered: 3; chat_history(chat_id=-1); chat_history(chat_id=-2)" in text
    assert "Quiet room [quiet]: silent; unanswered: 0; no captured room" in text
    assert "Paused room [paused]: paused; unanswered: unknown" in text
    assert calls == [(tmp_path, place.place_id) for place in configured]
    monkeypatch.setattr(places, "load_places", lambda root: [])
    assert view.places_text(view.place_views(tmp_path)) == "none"


def test_unavailable_index_does_not_claim_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(places, "load_places", lambda root: [places.Place("p", "c", "provider")])
    monkeypatch.delattr(places, "place_room_index", raising=False)
    assert view.place_views(tmp_path)[0]["unanswered"] is None
    assert "unknown" in view.places_text(view.place_views(tmp_path))
    assert "unknown" in view.places_text(None)


def test_prompt_carries_labels_counts_and_one_allowance():
    repo = pathlib.Path(__file__).resolve().parents[1]
    configured = [{"place_id": "mail", "label": "Inbox", "state": "active", "unanswered": 0, "rooms": []}]
    causes = view.cause_views([{"cause": "place:mail", "usd": 2.5, "unmetered_calls": 1}], configured)
    roots = view.root_views([{"task_id": "root", "title": "Study queue", "consciousness_cause": "started"}], configured)
    text = render_wake_message(repo, reason="heartbeat", last_wake_at=0, now=0, level="act", disabled_tools=[],
                               spent_usd=2.5, daily_usd=20, running=1, max_tasks=2, interval=900, events="nothing new",
                               spent_is_floor=True, spend_by_cause=causes, counted_roots=roots, places=configured)
    assert all("{" + placeholder + "}" not in text for placeholder in PLACEHOLDERS)
    assert "Inbox: at least $2.50 (1 unmetered calls)" in text
    assert "root: Study queue (started work)" in text
    assert "places: Inbox [mail]: active; unanswered: 0" in text
    assert "allowance known spend (last 24 h): at least 2.50 / 20.00 USD" in text


def test_recent_wakes_read_a_bounded_existing_index(monkeypatch, tmp_path):
    from ouroboros import task_store
    calls = []
    monkeypatch.setattr(task_store, "newest_ids", lambda root, *, limit: calls.append(limit) or ["focus", "owner", "own"])
    documents = {"focus": {"metadata": {"wake_cause": "focus", "focus": {"place_id": "mail"}}, "status": "completed"},
                 "owner": {"metadata": {}}, "own": {"metadata": {"wake_cause": "own_clock"}}}
    monkeypatch.setattr(task_store, "documents_by_ids", lambda root, ids: documents)
    rows = view.recent_wakes(tmp_path, [{"place_id": "mail", "label": "Inbox"}])
    assert calls == [50] and [row["task_id"] for row in rows] == ["focus", "own"]
    assert rows[0]["place_label"] == "Inbox" and rows[0]["first_reply_at"] is None
    assert rows[0]["cost_usd"] is None
