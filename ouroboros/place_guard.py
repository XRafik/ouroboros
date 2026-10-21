"""Dispatch-time refusals that follow from tool effects and place state.

The protected dispatch guard (``registry_guards._capability_resource_guard_result``)
asks ``dispatch_refusal`` once per call, the way it asks
``consciousness_authority.observe_argument_refusal``. Three rules live here:

* Advises (stored ``observe``): an extension or MCP call whose effect is not a
  declared read is refused, declared or not.
* Silent / Paused: a ``message`` or ``write`` aimed at such a place is refused
  from every focus (Main, tasks, schedules, wakes). A connector write whose
  target cannot be attributed is refused while any of that connector's places
  is Silent or Paused, and the reason says so.
* One author per conversation: a send into a conversation another turn is
  authoring is refused with that author's task id (hand the intent over with
  ``tell_task``).

Seam stub: allows everything until the package lands.
"""

from __future__ import annotations

from typing import Any, Mapping


def dispatch_refusal(ctx: Any, name: str, args: Mapping[str, Any], *, ext_tool: Any = None,
                     is_mcp: bool = False) -> str:
    """The refusal text for this call, ``""`` to allow."""
    return ""


def call_place_facts(ctx: Any, name: str, args: Mapping[str, Any], *, ext_tool: Any = None,
                     is_mcp: bool = False) -> dict[str, Any]:
    """Host facts about where a call lands, for the Supervisor's bundle.

    ``{"effect", "declared", "targets": {arg: [values]}, "place_id", "place_label",
    "place_state", "conversation_key"}``; ``{}`` when no place is involved.
    """
    return {}
