"""``POST /api/ui/holds``: a page names the foreign UI it held back when it opened.

The start ledger lives in the page (``web/modules/holds.js``): before a skill's page module, a skill's
module or route frame, or an app card Ouroboros wrote gets its first turn, the page writes the item's
key; a key the next page finds means the page did not outlive that start (it froze, crashed or was
closed within the settle second). That page holds the item and posts the keys it found, once. The host
names them in one System row (``system_type: "ui_hold"``) in the chat that owns them, the card's own chat
or Main for a skill's page code and widgets, so the owner reads it on every surface and Ouroboros reads
it in its next turn's context: a fact, never a reaction. A ``key@rev`` is named once per server process,
so another tab or device that finds the same hold adds no row.
"""

from __future__ import annotations

import logging
import pathlib
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from starlette.requests import Request
from starlette.responses import JSONResponse

from ouroboros.gateway._helpers import json_error, request_drive_root, request_json_or, run_sync_to_completion

log = logging.getLogger(__name__)

MAX_REPORTED_HOLDS = 64  # the ledger's own bound (web/modules/holds.js MAX_ENTRIES)
_KEY = re.compile(r"^(app|widget|module):\S{1,280}$")
_NAMED: "OrderedDict[str, None]" = OrderedDict()
_NAMED_MAX = 512


class _ChatUnavailable(RuntimeError):
    """No chat writer serves this data root (no running supervisor): nothing was written."""


def _surface_words(surface: Any) -> str:
    facts = surface if isinstance(surface, dict) else {}
    if facts.get("pywebview") is True:
        return "the desktop app"
    if facts.get("telegram") is True:
        return "the Telegram mini app"
    return "a browser"


def _item(root: pathlib.Path, key: str) -> Tuple[str, Optional[int]]:
    """The words for one held item and the chat that owns it (None: Main)."""
    kind, _, rest = key.partition(":")
    if kind == "app":
        from ouroboros.card_store import load_card

        record = load_card(root, rest)
        if record is None:
            return "", None
        chat_id = record.get("chat_id")
        return f"the card «{record.get('title') or rest}»", chat_id if isinstance(chat_id, int) else None
    if kind == "widget":
        skill, _, tab = rest.partition(":")
        return f"the {tab} widget of {skill}", None
    return f"the page code of {rest.partition(':')[0]}", None


def _name_holds(root: pathlib.Path, groups: Dict[Optional[int], List[str]], surface: str) -> int:
    from supervisor import message_bus
    from supervisor.schedule_notes import owner_chat_id

    data_root = message_bus.DATA_DIR
    if data_root is None or pathlib.Path(data_root).resolve() != root.resolve() or message_bus.try_get_bridge() is None:
        raise _ChatUnavailable("no chat writer serves this data root")
    for chat_id, items in groups.items():
        names = ", ".join(items)
        verb = "was" if len(items) == 1 else "were"
        message_bus.send_with_budget(
            chat_id if chat_id is not None else owner_chat_id(root),
            f"Held back on {surface}: the page stopped while {names} {verb} starting, so there it waits for the "
            "owner to start it again instead of starting by itself.",
            role="system", system_type="ui_hold",
        )
    return sum(len(items) for items in groups.values())


async def api_ui_holds_post(request: Request) -> JSONResponse:
    """``{"holds": [{"key", "rev"}], "surface": {"pywebview", "telegram"}}`` → ``200 {ok, named}``.

    ``400`` a body that is not this shape; ``503`` no chat writer: nothing was named."""
    body = await request_json_or(request, None)
    holds = body.get("holds") if isinstance(body, dict) else None
    if not isinstance(holds, list) or len(holds) > MAX_REPORTED_HOLDS:
        return json_error(f"holds must be a list of at most {MAX_REPORTED_HOLDS} items", 400)
    root = request_drive_root(request)
    groups: Dict[Optional[int], List[str]] = {}
    fresh: List[str] = []
    for hold in holds:
        key = hold.get("key") if isinstance(hold, dict) else None
        if not isinstance(key, str) or not _KEY.match(key):
            return json_error("each hold needs a key: app:, widget: or module:", 400)
        marker = f"{key}@{str(hold.get('rev') or '')[:128]}"
        if marker in _NAMED or marker in fresh:
            continue
        words, chat_id = _item(root, key)
        if words:
            groups.setdefault(chat_id, []).append(words)
            fresh.append(marker)
    if not groups:
        return JSONResponse({"ok": True, "named": 0})
    try:
        named = await run_sync_to_completion(_name_holds, root, groups, _surface_words(body.get("surface")))
    except _ChatUnavailable as exc:
        return json_error(str(exc), 503, reason_code="chat_unavailable")
    for marker in fresh:
        _NAMED[marker] = None
    while len(_NAMED) > _NAMED_MAX:
        _NAMED.popitem(last=False)
    return JSONResponse({"ok": True, "named": named})


__all__ = ["MAX_REPORTED_HOLDS", "api_ui_holds_post"]
