"""Materialize the permitted completion schema when finalization needs the front door."""
from __future__ import annotations
from typing import Any

def completion_schema(tools: Any, schemas: list | None = None) -> str:
    """Materialize the current permitted front door, including cold/Nano holds."""
    from ouroboros.usage_accounting import invalidate_task_cache_splits
    ctx = tools._ctx
    name = "finish_task"
    getter = getattr(tools, "get_schema_by_name", None)
    if not callable(getter):
        return name
    schema = getter(name)
    if schema is None:
        return "no currently permitted completion tool"
    if schemas is not None and not any(row.get("function", {}).get("name") == name for row in schemas):
        schemas.append(schema)
        invalidate_task_cache_splits(getattr(ctx, "task_id", ""))
        getattr(ctx, "messages", []).append({"role": "user", "content":
            "[SYSTEM NOTICE] Current permitted completion schema loaded: " + name + ". The schema prefix changed."})
    return name


