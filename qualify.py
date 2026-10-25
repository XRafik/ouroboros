#!/usr/bin/env python3
"""Opt-in, secretless #1234 diagnostic. No runtime/Playwright imports in parse mode."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import resource
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import traceback

MODES = ("direct-fresh", "direct-reuse", "runtime-owner")
MARKER = "OBO1234_LOCAL_PAGE_OK"
URL = "data:text/html,<title>issue1234</title><body>" + MARKER + "</body>"
# Values only for these non-credential keys; no ambient environment is forwarded.
LOADER_KEYS = ("LD_LIBRARY_PATH", "LD_LIBRARY_PATH_ORIG", "LD_PRELOAD")
ENV_KEYS = LOADER_KEYS + ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "XDG_CACHE_HOME",
                         "XDG_CONFIG_HOME", "PYTHONPATH", "PYTHONNOUSERSITE",
                         "PYTHONDONTWRITEBYTECODE", "PLAYWRIGHT_BROWSERS_PATH", "DEBUG",
                         "OUROBOROS_APP_ROOT", "OUROBOROS_DATA_DIR", "OUROBOROS_REPO_DIR")


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_debug(text):
    """Parse observations, not verdicts. Missing exit/launch lines remain missing."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    launches, exits, errors = [], [], []
    for line in text.splitlines():
        if "<launching> " in line:
            command = line.split("<launching> ", 1)[1]
            try:
                launches.append(shlex.split(command))
            except ValueError:
                errors.append({"kind": "unparsed_launch", "line": line})
        match = re.search(r"\[pid=(\d+)\].*<process did exit: exitCode=([^,]+), signal=([^>]+)>", line)
        if match:
            exits.append(dict(zip(("pid", "exit_code", "signal"), match.groups())))
    return {"launch_argv": launches, "browser_exits": exits, "parse_errors": errors,
            "sigtrap_observed": any(e["signal"].strip() == "SIGTRAP" for e in exits),
            "abnormal_exits": [e for e in exits if e["signal"].strip() != "null" or e["exit_code"].strip() != "0"],
            "check_failed_lines": [s for s in text.splitlines() if "Check failed" in s],
            "coverage": "debug lines only; short-lived processes may escape /proc sampling"}


def loader_values(path):
    values = json.loads(Path(path).read_text()) if path else {}
    if not isinstance(values, dict) or set(values) - set(LOADER_KEYS):
        raise ValueError("loader JSON may contain only " + ", ".join(LOADER_KEYS))
    if any(not isinstance(v, str) or "\n" in v or "://" in v for v in values.values()):
        raise ValueError("loader values must be single-line, credential-free local paths")
    return values  # Missing and present-but-empty remain different.


def environment(case, source, loader):
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "PYTHONPATH": str(source), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PLAYWRIGHT_BROWSERS_PATH": "0", "DEBUG": "pw:browser",
           "OUROBOROS_REPO_DIR": str(source), "OUROBOROS_APP_ROOT": str(case / "app"),
           "OUROBOROS_DATA_DIR": str(case / "drive")}
    for key, name in (("HOME", "home"), ("TMPDIR", "tmp"), ("XDG_CACHE_HOME", "cache"),
                      ("XDG_CONFIG_HOME", "config")):
        directory = case / name
        directory.mkdir()
        env[key] = str(directory)
    env.update(loader)
    return env


def proc_snapshot(pgid, out, seen):
    """Read maps/argv/allowlisted environment of OUR new process group only."""
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) != pgid:  # state, ppid, pgrp, ...
                continue
            identity = (directory.name, fields[19])  # pid + starttime, not PID alone
            if identity in seen:
                continue
            exe = os.readlink(directory / "exe")
            if "chrome" not in Path(exe).name and Path(exe).name != "node":
                continue
            seen.add(identity)
            raw = (directory / "environ").read_bytes().split(b"\0")
            values = dict(item.decode(errors="replace").split("=", 1) for item in raw if b"=" in item)
            dump(out / (directory.name + ".json"), {
                "pid": int(directory.name), "starttime_ticks": fields[19], "exe": exe,
                "argv": (directory / "cmdline").read_bytes().decode(errors="replace").split("\0"),
                "environment": {k: values[k] for k in ENV_KEYS if k in values}})
            (out / (directory.name + ".maps")).write_text((directory / "maps").read_text())
        except (FileNotFoundError, ProcessLookupError):
            pass  # A sampled process exited; DEBUG evidence remains independent.
        except (PermissionError, OSError, ValueError) as exc:
            with (out / "sampling-errors.log").open("a") as stream:
                stream.write(type(exc).__name__ + ": " + str(exc) + "\n")


def worker(args):
    case, source, bundle = Path(args.out), Path(args.source), Path(args.bundle)
    # No installation, Python child, external model or shell is needed by these owners.
    # Retain the real owner code; audit-deny unexpected subprocesses rather than repair it.
    import playwright
    pw_root = Path(playwright.__file__).resolve().parent
    pw_root.relative_to(bundle)
    headless = list((pw_root / "driver/package/.local-browsers").glob(
        "chromium_headless_shell-*/chrome-headless-shell-linux*/chrome-headless-shell"))
    if len(headless) != 1:
        raise RuntimeError("expected exactly one RELEASE bundled Linux headless-shell: " + str(headless))
    binary = headless[0].resolve()
    with binary.open("rb") as stream:
        header = stream.read(20)
    if header[:4] != b"\x7fELF" or header[5] != 1 or struct.unpack("<H", header[18:20])[0] != 62:
        raise RuntimeError("headless-shell is not little-endian ELF x86_64")
    node = (pw_root / "driver/node").resolve()

    def audit(event, values):
        if event == "subprocess.Popen":
            executable, argv, _cwd, _env = values
            # Playwright's own node driver is the ONLY permitted subprocess here.
            if Path(executable).resolve() != node or list(argv)[1:] != [str(pw_root / "driver/package/cli.js"), "run-driver"]:
                raise RuntimeError("QA denied unexpected subprocess (no downloads/installs/models): " + str(executable))
    sys.addaudithook(audit)
    soft, hard = resource.getrlimit(resource.RLIMIT_CORE)
    cap = args.core_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_CORE, (min(cap, hard) if hard >= 0 else cap, hard))
    dump(case / "identity.json", {
        "python": sys.executable, "python_sha256": sha(sys.executable), "python_version": sys.version,
        "playwright_module": str(pw_root), "playwright_version": importlib.metadata.version("playwright"),
        "browser": str(binary), "browser_sha256": sha(binary),
        "browser_registry": json.loads((pw_root / "driver/package/browsers.json").read_text()),
        "environment": {k: os.environ[k] for k in ENV_KEYS if k in os.environ},
        "core_limit_before": [soft, hard], "core_limit_effective": list(resource.getrlimit(resource.RLIMIT_CORE)),
        "scope": "released browser owner in a QA process; NOT a frozen launcher/server reproduction"})
    from playwright.sync_api import sync_playwright
    observations = []

    def observe(value):
        observations.append(value)
        with (case / "steps.jsonl").open("a") as stream:
            stream.write(json.dumps(value) + "\n")  # Retain successful/failed steps before any later exception.

    if args.mode.startswith("direct"):
        with sync_playwright() as pw:
            browser = None
            try:
                for index in range(args.cycles):
                    if browser is None:
                        browser = pw.chromium.launch(headless=True)
                    context = browser.new_context()
                    try:
                        page = context.new_page()
                        page.goto(URL, timeout=10000, wait_until="domcontentloaded")
                        assert MARKER in page.inner_text("body")
                        observe({"index": index, "ok": True, "thread_id": threading.get_ident(), "version": browser.version})
                    finally:
                        context.close()
                    if args.mode == "direct-fresh":
                        browser.close()
                        browser = None
            finally:
                if browser is not None:
                    browser.close()
    else:
        from ouroboros.tools import browser as owner
        from ouroboros.tools.registry import ToolContext
        from ouroboros.tools.tool_result import LegacyTextResultAdapter, ToolResult
        from ouroboros.loop_tool_execution import StatefulToolExecutor, _execute_with_timeout
        ctx = ToolContext(repo_dir=source, drive_root=case / "drive", task_id="issue1234-qa")
        ctx.drive_logs().mkdir(parents=True, exist_ok=True)
        # Only replace the registry boundary, NOT the browser manager or executor.
        # Full registry safety/extension/provider machinery is intentionally not run.
        class BrowserOnlyDispatch:
            CODE_TOOLS = frozenset()
            _ctx = ctx

            def execute_result(self, name, values):
                assert name == "browse_page"
                text = owner._browse_page(ctx, **values)
                observe({"index": len(observations), "ok": MARKER in str(text), "thread_id": threading.get_ident(),
                         "generation_id": id(ctx.browser_state), "text": str(text)})
                return text if isinstance(text, ToolResult) else LegacyTextResultAdapter.from_text(name, text)
        executor = StatefulToolExecutor()
        try:
            for index in range(args.cycles):
                tc = {"id": "qa-" + str(index), "function": {"name": "browse_page", "arguments": json.dumps(
                    {"url": URL, "output": "text", "timeout": 10000})}}
                result = _execute_with_timeout(BrowserOnlyDispatch(), tc, ctx.drive_logs(),
                                               20, ctx.task_id, executor)
                if result.get("is_error") or MARKER not in result.get("result", ""):
                    raise RuntimeError("owner returned unsuccessful observation: " + str(result.get("result")))
        finally:
            # Cleanup on the REAL sticky owner thread. The outer process deadline
            # kills this whole new process group if a timeout/cleanup never settles.
            executor.submit(owner.cleanup_browser, ctx).result(timeout=10)
            executor.shutdown(wait=True)
    dump(case / "result.json", {"completed_steps": len(observations), "steps": observations,
                                "effective_environment": {k: os.environ[k] for k in ENV_KEYS if k in os.environ},
                                "main_thread_id": threading.get_ident()})


def run(args):
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise RuntimeError("execution requires Linux x86_64; this is not an emulation qualifier")
    source, bundle = Path(args.source).resolve(), Path(args.bundle).resolve()
    python = bundle / "python-standalone/bin/python3"
    if not python.is_file():
        raise RuntimeError("missing explicit release embedded Python: " + str(python))
    source_sha = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if source_sha != args.expected_source_sha or subprocess.check_output(
            ["git", "--no-optional-locks", "-C", str(source), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("source must be a clean checkout of expected-source-sha")
    out = Path(args.out).resolve()
    out.mkdir(mode=0o700)  # Existing evidence is NEVER overwritten.
    inherited = loader_values(args.loader_env)
    source_files = ("ouroboros/tools/browser.py", "ouroboros/loop_tool_execution.py",
                    "ouroboros/tools/tool_context.py")
    dump(out / "host.json", {"uname": list(platform.uname()), "source_sha": source_sha,
         "source_hashes": {p: sha(source / p) for p in source_files},
         "os_release": Path("/etc/os-release").read_text(),
         "core_pattern": Path("/proc/sys/kernel/core_pattern").read_text().strip(),
         "diagnostic_tools": {n: shutil.which(n) for n in ("coredumpctl", "gdb", "readelf", "ldd")},
         "conditions": "secretless QA HOME/env; core limit opt-in; no TLS/graphics overrides; no launcher"})
    summary = []
    for mode in MODES:
        case = out / mode
        case.mkdir(mode=0o700)
        (case / "proc").mkdir()
        env = environment(case, source, inherited)
        command = [str(python), str(Path(__file__).resolve()), "_worker", "--mode", mode,
                   "--source", str(source), "--bundle", str(bundle), "--out", str(case),
                   "--cycles", str(args.cycles), "--core-mib", str(args.core_mib)]
        dump(case / "invocation.json", {"argv": command, "environment": env, "deadline_sec": args.case_seconds,
                                       "started_at_utc": datetime.now(timezone.utc).isoformat()})
        start = time.monotonic()
        with (case / "stdout.log").open("wb") as stdout, (case / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=case, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            reason, seen = "exited", set()
            try:
                while process.poll() is None:
                    proc_snapshot(process.pid, case / "proc", seen)
                    if time.monotonic() - start > args.case_seconds:
                        reason = "case_deadline"
                        break
                    if max((case / "stdout.log").stat().st_size, (case / "stderr.log").stat().st_size) > 16 * 1024**2:
                        reason = "log_limit_16MiB"
                        break
                    time.sleep(0.1)
            finally:
                # Session belongs solely to this worker. Kill residual children on
                # success too; never kill by executable name or unrelated PID.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        debug = parse_debug((case / "stderr.log").read_text(errors="replace"))
        dump(case / "browser-debug.json", debug)
        identity = json.loads((case / "identity.json").read_text()) if (case / "identity.json").exists() else {}
        result = json.loads((case / "result.json").read_text()) if (case / "result.json").exists() else {}
        steps = [json.loads(line) for line in (case / "steps.jsonl").read_text().splitlines()] if (case / "steps.jsonl").exists() else []
        matched = bool(debug["launch_argv"]) and bool(identity) and all(
            argv and str(Path(argv[0]).resolve()) == identity["browser"] for argv in debug["launch_argv"])
        summary.append({"mode": mode, "worker_exit": process.returncode, "stop_reason": reason,
                        "elapsed_sec": round(time.monotonic() - start, 3),
                        "completed_steps": result.get("completed_steps", sum(bool(s.get("ok")) for s in steps)),
                        "worker_result_complete": bool(result), "abnormal_browser_exits": debug["abnormal_exits"],
                        "actual_bundle_browser_matched": matched, "sigtrap_observed": debug["sigtrap_observed"],
                        "browser_exit_lines": len(debug["browser_exits"])})
    same = [json.loads((out / m / "identity.json").read_text()) for m in MODES if (out / m / "identity.json").exists()]
    comparable = len(same) == len(MODES) and len({(r["python_sha256"], r["browser_sha256"], r["playwright_module"]) for r in same}) == 1
    environments = {m: json.loads((out / m / "invocation.json").read_text())["environment"] for m in MODES}
    differences = {k: {m: environments[m].get(k) for m in MODES} for k in ENV_KEYS
                   if len({environments[m].get(k) for m in MODES}) > 1}
    dump(out / "summary.json", {"same_bundle_identity": comparable, "cases": summary,
         "initial_environment_differences": differences,
         "interpretation": "bounded observations, never proof of a fix or Silverblue reproduction"})
    return 0 if comparable and all(r["worker_exit"] == 0 and r["actual_bundle_browser_matched"] and
        r["worker_result_complete"] and r["completed_steps"] == args.cycles and not r["abnormal_browser_exits"] and
        r["browser_exit_lines"] > 0 for r in summary) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    parse = commands.add_parser("parse", help="OFFLINE: parse an existing pw:browser stderr log")
    parse.add_argument("log")
    for command in ("run", "_worker"):
        sub = commands.add_parser(command)
        for name in ("source", "bundle", "out"):
            sub.add_argument("--" + name, required=True)
        sub.add_argument("--cycles", type=int, choices=range(1, 11), default=3)
        sub.add_argument("--core-mib", type=int, choices=range(0, 65), default=0)
        if command == "run":
            sub.add_argument("--expected-source-sha", required=True)
            sub.add_argument("--case-seconds", type=int, choices=range(30, 121), default=60)
            sub.add_argument("--loader-env", help="optional explicit JSON of credential-free loader paths; used identically in all arms")
        else:
            sub.add_argument("--mode", choices=MODES, required=True)
    args = parser.parse_args()
    if args.command == "parse":
        print(json.dumps(parse_debug(Path(args.log).read_text(errors="replace")), indent=2))
        return 0
    return run(args) if args.command == "run" else worker(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
