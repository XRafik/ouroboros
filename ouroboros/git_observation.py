"""Host Git observations: no index writes and content-confirmed changed paths."""

from __future__ import annotations

import os
import re
from typing import Callable, Dict, Optional, Sequence, Union


def numstat_paths(output: Union[str, bytes], command: Sequence[str],
                  read: Callable[[Sequence[str]], Union[str, bytes]]) -> list[str]:
    """Read ``--numstat -z`` paths, confirming binary rows through the same reader.

    Without index refresh, Git can emit ``-\t-`` for identical binary bytes.
    A plain patch compares content and emits only a binary summary (no --binary
    payload); it also preserves mode changes and both sides of renames/copies.
    Keep the comparison's refs/options but scope each probe to literal paths.
    """
    if isinstance(output, bytes):
        output = output.decode("utf-8", "surrogateescape")
    fields, paths = iter(output.split("\0")), []
    scope = list(command[:command.index("--")] if "--" in command else command)
    probe = [arg for arg in scope if arg not in {"--numstat", "-z"}]
    probe.extend(["--patch", "--no-ext-diff", "--no-textconv", "--"])
    for row in fields:
        if not row:
            continue
        added, deleted, path = row.split("\t", 2)
        sources = [path] if path else [next(fields), next(fields)]
        if added == deleted == "-" and not read([*probe, *(f":(literal){p}" for p in sources)]):
            continue
        paths.append(sources[-1])
    return paths


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
