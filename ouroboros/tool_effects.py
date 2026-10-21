"""What a tool call does to the world outside Ouroboros: one fact, three consumers.

A connector declares each of its tools in the manifest's ``tools:`` list with
``effect: read | message | write`` (absent = ``write``) and, where it has one,
``target:`` — the argument(s) naming where the effect lands. ``message`` means
words to people at the target; ``write`` is any other change outside. The
declaration is read from the reviewed, published generation the dispatcher
uses, never from the mutable skill folder. MCP tools carry no declaration:
they are ``write`` with ``declared=False``, and their annotations can only
make a call stricter. A mixed tool (one tool that reads or writes depending on
its arguments) is ``write``.

Consumers: the Advises refusal (``place_guard``), Silent/Paused refusal of
writes aimed at a place (``place_guard``), and the Supervisor (``safety``:
declared reads skip Light/Full checks; ``message`` gets the speech semantics).
Built-in tools are governed by their own policy tables and answer ``""``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

EFFECT_READ = "read"
EFFECT_MESSAGE = "message"
EFFECT_WRITE = "write"
EFFECTS = (EFFECT_READ, EFFECT_MESSAGE, EFFECT_WRITE)


@dataclass(frozen=True)
class ToolEffect:
    """The effect fact of one tool name.

    ``effect`` is ``""`` for a built-in tool (not governed here). ``targets``
    names the arguments that carry the destination(s): a list covers e.g.
    to/cc/bcc. ``conversation``/``thread`` name the arguments that address a
    conversation, when the connector declared them. ``declared`` is False when
    the effect is the default (no declaration, MCP, unreadable manifest).
    """

    effect: str
    targets: tuple[str, ...] = ()
    conversation: str = ""
    thread: str = ""
    declared: bool = False
    source: str = ""
    annotations: Mapping[str, Any] = field(default_factory=dict)


BUILTIN = ToolEffect(effect="", source="builtin")


def effect_of(name: str, *, ext_tool: Any = None, is_mcp: bool = False, ctx: Any = None) -> ToolEffect:
    """The effect fact of ``name`` for this dispatch.

    Seam stub: every extension and MCP tool is an undeclared write until the
    declaration reader lands.
    """
    if is_mcp:
        return ToolEffect(effect=EFFECT_WRITE, declared=False, source="mcp")
    if ext_tool is not None:
        return ToolEffect(effect=EFFECT_WRITE, declared=False, source="extension")
    return BUILTIN


def target_values(effect: ToolEffect, args: Mapping[str, Any]) -> dict[str, list[str]]:
    """The declared target argument values of one call, by argument name (strings only)."""
    values: dict[str, list[str]] = {}
    source = args if isinstance(args, Mapping) else {}
    for name in (*effect.targets, effect.conversation, effect.thread):
        if not name or name in values:
            continue
        raw = source.get(name)
        items = raw if isinstance(raw, (list, tuple)) else [raw]
        texts = [str(item).strip() for item in items if isinstance(item, (str, int)) and str(item).strip()]
        if texts:
            values[name] = texts
    return values
