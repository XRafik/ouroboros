"""Shared Git environment for host observations, including runtime-only entrypoints."""

from __future__ import annotations

import os
import re
from typing import Dict, Optional


def host_git_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Disable optional locks and diff refresh without disabling writer locks.

    Append invocation config instead of replacing the caller's Git settings.
    Git ignores an empty count; invalid counts must reach Git unchanged so its
    ordinary return code and stderr, rather than a Python exception, describe it.
    """
    result = dict(os.environ if env is None else env)
    result.update(LC_ALL="C", LANG="C", GIT_OPTIONAL_LOCKS="0")
    count = result.get("GIT_CONFIG_COUNT") or "0"
    # Git parses an ASCII decimal with strtoul, not Python's Unicode/underscore
    # integer syntax. Preserve invalid input for Git's own diagnostic.
    if re.fullmatch(r"[ \t\r\n\v\f]*[+-]?[0-9]+", count) is None:
        return result
    try:
        slot = int(count)
    except ValueError:
        return result
    if slot < 0:
        return result
    result["GIT_CONFIG_COUNT"] = str(slot + 1)
    result[f"GIT_CONFIG_KEY_{slot}"] = "diff.autoRefreshIndex"
    result[f"GIT_CONFIG_VALUE_{slot}"] = "false"
    return result
