"""One author per conversation, across processes, and the physical bound on conversations.

Today's Presence gate generalized: a turn authoring a place conversation holds
that conversation's lease (a process-local lock plus a cross-process file lock,
lendable at a qualified review wait), and at most N conversations run at once
(``OUROBOROS_PRESENCE_MAX_ACTIVE``, shown as "Concurrent conversations").

Seam stub: no live authors until the package lands.
"""

from __future__ import annotations

from typing import Any


def live_author(conversation_key: str, *, drive_root: Any = None) -> str:
    """The task id authoring this conversation now, ``""`` when none."""
    return ""


def live_authors(*, drive_root: Any = None) -> list[str]:
    """Every task id authoring a place conversation in this process now (Stop reaches them)."""
    return []
