"""Places: where Ouroboros lives outside Main, one host record per place.

A place is what a connector skill connects (a Slack workspace, a Telegram
group, an email inbox). The owner's choices about it live in ONE host record
(``data/state/places.json``), never in the connector: its state (Active ·
Silent · Paused), its wake list (typed event facts and who added each), notes
(with per-entry authorship), the owner's confirmed accounts there, a working
folder (an address, not a fence) and an optional model. A connector update
never overwrites these choices.

Seam stub: the public names below are the contract other packages code
against; the store, migration and writers land with the places package.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

PLACES_FILENAME = "places.json"

STATE_ACTIVE, STATE_SILENT, STATE_PAUSED = "active", "silent", "paused"
PLACE_STATES = (STATE_ACTIVE, STATE_SILENT, STATE_PAUSED)

# Typed event facts a connector attaches to an event (``event.facts``). The wake
# list is a set of these kinds; code matches facts, never message text.
FACT_DIRECT_MESSAGE = "direct_message"      # a 1:1 message to Ouroboros
FACT_GROUP_DM = "group_dm"                  # a group DM Ouroboros is in
FACT_MENTION = "mention"                    # mentions Ouroboros
FACT_REPLY_TO_ME = "reply_to_me"            # a reply to Ouroboros's message
FACT_MY_THREAD = "my_thread"                # a reply in a thread Ouroboros is in
FACT_NEW_ISSUE = "new_issue"                # a new issue (code hosts)
FACT_NEW_PULL_REQUEST = "new_pull_request"  # a new pull request (code hosts)
FACT_ANY_MESSAGE = "any_message"            # every message
FACT_FROM_BOT = "from_bot"                  # the author is a bot (matches only when listed itself)
WAKE_FACTS = (
    FACT_DIRECT_MESSAGE, FACT_GROUP_DM, FACT_MENTION, FACT_REPLY_TO_ME, FACT_MY_THREAD,
    FACT_NEW_ISSUE, FACT_NEW_PULL_REQUEST, FACT_ANY_MESSAGE, FACT_FROM_BOT,
)
# An event from a connector that predates typed facts: it already sent only
# what its old binding admitted, so it counts as addressed.
FACT_LEGACY_ADDRESSED = "legacy_addressed"

# Who added a wake item or a note.
AUTHOR_CONNECTOR, AUTHOR_OWNER, AUTHOR_OUROBOROS, AUTHOR_MIGRATION = (
    "connector", "owner", "ouroboros", "migration")


@dataclass(frozen=True)
class WakeItem:
    fact: str
    author: str


@dataclass(frozen=True)
class NoteEntry:
    text: str
    author: str
    at: str = ""


@dataclass(frozen=True)
class OwnerAccount:
    platform_actor_id: str
    label: str = ""
    confirmed_at: str = ""


@dataclass(frozen=True)
class Place:
    place_id: str
    connector: str              # the connector skill's canonical name
    provider: str               # the transport/provider id the connector reports (e.g. "slack")
    account_id: str = ""        # "" = any account this connector serves
    conversation_id: str = ""   # "" = the whole account
    label: str = ""
    state: str = STATE_ACTIVE
    wakes: tuple[WakeItem, ...] = ()
    notes: tuple[NoteEntry, ...] = ()
    owner_accounts: tuple[OwnerAccount, ...] = ()
    working_folder: str = ""
    model: str = ""             # "" = the consciousness model
    context_topics: tuple[str, ...] = ()
    legacy_binding_ids: tuple[str, ...] = ()
    revision: int = 0


def load_places(drive_root: Any) -> list[Place]:
    """Every place record (seam stub: none)."""
    return []


def resolve_place(drive_root: Any, *, connector: str, provider: str = "", account_id: str = "",
                  conversation_id: str = "", binding_id: str = "") -> Place | None:
    """The most specific place for an event, or the place an old binding id migrated to."""
    return None


def places_of_connector(drive_root: Any, connector: str) -> list[Place]:
    """Every place a connector serves."""
    return [place for place in load_places(drive_root) if place.connector == connector]


def wake_matches(place: Place, facts: Iterable[str]) -> tuple[WakeItem, ...]:
    """The wake items an event's typed facts match (empty: it is heard, not woken for)."""
    present = {str(fact) for fact in facts}
    if FACT_LEGACY_ADDRESSED in present:
        return (WakeItem(FACT_LEGACY_ADDRESSED, AUTHOR_CONNECTOR),)
    if FACT_FROM_BOT in present and not any(item.fact == FACT_FROM_BOT for item in place.wakes):
        return ()
    return tuple(item for item in place.wakes
                 if item.fact in present or (item.fact == FACT_ANY_MESSAGE and present - {FACT_FROM_BOT}))


def is_owner_account(place: Place, platform_actor_id: str) -> bool:
    """Whether the owner confirmed this platform account as his own in this place."""
    actor = str(platform_actor_id or "").strip()
    return bool(actor) and any(account.platform_actor_id == actor for account in place.owner_accounts)


def place_summary(place: Place) -> Mapping[str, Any]:
    """The JSON projection the gateway and the mind read."""
    return {
        "place_id": place.place_id, "connector": place.connector, "provider": place.provider,
        "account_id": place.account_id, "conversation_id": place.conversation_id,
        "label": place.label, "state": place.state,
        "wakes": [{"fact": item.fact, "author": item.author} for item in place.wakes],
        "notes": [{"text": note.text, "author": note.author, "at": note.at} for note in place.notes],
        "owner_accounts": [{"platform_actor_id": a.platform_actor_id, "label": a.label,
                            "confirmed_at": a.confirmed_at} for a in place.owner_accounts],
        "working_folder": place.working_folder, "model": place.model,
    }


def places_path(drive_root: Any) -> Path:
    return Path(drive_root) / "state" / PLACES_FILENAME
