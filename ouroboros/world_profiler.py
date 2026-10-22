"""My map of my world (`memory/WORLD.md`): a measured block the host refreshes at every
startup, and the rest, which is mine.

``generate_world_profile`` writes a fresh file. ``refresh_world_profile`` rewrites only the
fenced measured block in place and never touches the text outside it; a legacy first-boot
profile is fenced once. ``with_measured_block`` keeps the host's block when the mind
publishes the file through ``update_world``. The measured facts are a probe at startup,
not a census of the environment: what lives here is the mind's to record.
"""
import os
import platform
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ouroboros.platform_layer import (
    bootstrap_process_path,
    get_cpu_info,
    get_system_memory,
    node_runtime_health,
    resolve_bundled_node,
)

MEASURED_START = "<!-- measured -->"
MEASURED_END = "<!-- /measured -->"
# The context section budget for the loaded map (a warning, never a trim).
WORLD_SECTION_BUDGET_CHARS = 16_000
_FENCE_RE = re.compile(re.escape(MEASURED_START) + r".*?" + re.escape(MEASURED_END), re.S)
_LEGACY_FOOTER = "*(Generated automatically on first boot)*"
_LEGACY_MEASURED_HEAD = "## System"
TITLE = "# WORLD.md — My map of my world"
_INTRO = (
    "The measured block below is the host's and refreshes at every startup; everything outside it is "
    "mine to keep current with `update_world`: what lives here, how I reach it, what worked, what is "
    "held or refused (compact; detail in `memory/knowledge/`)."
)
_OWN_SEED = (
    "## What lives here\n\n"
    "_(Mine to fill: agents, services, hosts, devices and the channels to each, dated.)_\n"
)


def _resolved_roots(repo_dir: str, data_dir: str) -> tuple[str, str]:
    """The file-system rules name the roots this installation actually uses; a caller
    without them resolves the configured ones (``ouroboros.config``)."""
    if repo_dir and data_dir:
        return repo_dir, data_dir
    from ouroboros.config import resolve_data_dir, resolve_repo_dir

    return repo_dir or str(resolve_repo_dir()), data_dir or str(resolve_data_dir())


def _tools_found() -> list[str]:
    # Check for CLI tools against the PATH the tool subprocesses will actually
    # see (the shell/verify surfaces bootstrap before resolving).
    bootstrap_process_path()
    # `which` success is not runnability: a corrupted PATH node is SIGKILLed on
    # launch, so WORLD.md must not enshrine it — or the npm that starts through
    # `#!/usr/bin/env node` — as usable. Probe node ONCE up front; npm below is
    # gated on a usable node (PATH-healthy, or the bundled emergency fallback).
    node_path = shutil.which("node")
    node_health = node_runtime_health(node_path, timeout_sec=3) if node_path else None
    path_node_ok = bool(node_health is not None and node_health.healthy)
    bundled_ok = False
    if not path_node_ok:
        # Consulted lazily: a healthy PATH node needs no bundle at all.
        bundled = resolve_bundled_node()
        bundled_ok = bool(bundled) and node_runtime_health(bundled, timeout_sec=3).healthy
    node_usable = path_node_ok or bundled_ok
    tools = []
    for tool in ["git", "python3", "python", "pip", "npm", "node", "claude"]:
        located = shutil.which(tool)
        if tool == "node":
            if node_health is not None and node_health.healthy:
                tools.append(tool)
            elif node_path and node_health is not None and node_health.status == "broken":
                # Only a PROBED failure earns the broken label; a stat-level
                # miss (vanished/not-executable) reads as absent, like any
                # other missing tool (T16).
                suffix = "; bundled fallback available)" if bundled_ok else ")"
                tools.append(f"node (broken: {node_health.reason or node_health.status}{suffix}")
            elif bundled_ok:
                tools.append("node (bundled fallback available)")
            continue
        if tool == "npm" and located and not node_usable:
            tools.append("npm (needs a working node)")
            continue
        if located:
            tools.append(tool)
    return tools


def measured_block(repo_dir: str = "", data_dir: str = "") -> str:
    """The host's fenced block: system facts, a probe of common binaries and the roots in use."""
    repo_dir, data_dir = _resolved_roots(repo_dir, data_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    return f"""{MEASURED_START}
## System (measured at startup, {stamp})
- **OS**: {platform.system()} {platform.release()} ({platform.machine()})
- **CPU**: {get_cpu_info()}
- **RAM**: {get_system_memory()}
- **User**: {user}
- **Current Directory**: {os.getcwd()}

## Tools found on PATH at startup
A probe of common binaries, not a census of what lives here:
`{', '.join(_tools_found())}`

## File System Rules
- `{repo_dir}` contains my codebase.
- `{data_dir}` contains my memory, state, and logs.
I should generally confine my writes to these directories, though I have read access to the rest of the filesystem if needed for exploration.
{MEASURED_END}"""


def _fresh_profile(block: str) -> str:
    return f"{TITLE}\n\n{_INTRO}\n\n{block}\n\n{_OWN_SEED}"


def _splice(text: str, block: str) -> str:
    """Replace the measured block in ``text`` and keep everything else byte for byte.

    A legacy first-boot profile (no fence) is fenced once: its generated span becomes the
    block, any text the mind added after the old footer stays. Unrecognized text keeps its
    first title line and gets the block right after it: nothing is ever dropped.
    """
    if _FENCE_RE.search(text):
        return _FENCE_RE.sub(lambda _m: block, text, count=1)
    head_at = text.find(_LEGACY_MEASURED_HEAD)
    foot_at = text.find(_LEGACY_FOOTER)
    if text.startswith("# WORLD.md") and 0 <= head_at < foot_at:
        tail = text[foot_at + len(_LEGACY_FOOTER):].strip()
        return f"{TITLE}\n\n{_INTRO}\n\n{block}\n\n{tail or _OWN_SEED.rstrip()}\n"
    first_line, newline, rest = text.partition("\n")
    if first_line.startswith("# "):
        return f"{first_line}\n\n{block}\n\n{rest.lstrip()}"
    return f"{block}\n\n{text}"


def with_measured_block(content: str, old: str) -> str:
    """The mind's publication of the file, with the host's measured block kept or restored."""
    kept = _FENCE_RE.search(old)
    block = kept.group(0) if kept else measured_block()
    if _FENCE_RE.search(content):
        return _FENCE_RE.sub(lambda _m: block, content, count=1)
    first_line, _newline, rest = content.partition("\n")
    if first_line.startswith("# "):
        return f"{first_line}\n\n{block}\n\n{rest.lstrip()}"
    return f"{block}\n\n{content}"


def generate_world_profile(output_path: str, repo_dir: str = "", data_dir: str = ""):
    """Write a fresh WORLD.md: title, the measured block and an empty map for the mind."""
    content = _fresh_profile(measured_block(repo_dir, data_dir))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


def refresh_world_profile(output_path: str, repo_dir: str = "", data_dir: str = "") -> bool:
    """Rewrite only the measured block of an existing WORLD.md (generate a missing one).

    Returns True when the file changed."""
    from ouroboros.utils import write_bytes_atomic

    path = Path(output_path)
    if not path.exists():
        generate_world_profile(output_path, repo_dir, data_dir)
        return True
    # No newline translation: the text around the block is the mind's, byte for byte.
    with path.open("r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    spliced = _splice(text, measured_block(repo_dir, data_dir))
    if spliced == text:
        return False
    write_bytes_atomic(path, spliced.encode("utf-8"))
    return True


if __name__ == "__main__":
    generate_world_profile("WORLD.md")
