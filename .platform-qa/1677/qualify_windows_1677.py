#!/usr/bin/env python3
"""Secretless native Windows #1677 witness; execute ONLY beneath safe_test.

No product modules are imported at module load. This is an experiment, not a
product installer or a general test framework. Only its fresh private prefix is
mutable. The parent owns dispatch and the interpretation of every result.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

PHASES = (
    "boundary_and_source", "packaged_node_fixture", "legacy_live_reader",
    "initial_private_start", "check_latest_installs_nothing",
    "update_prepares_only", "preparation_preserves_live_process",
    "repeat_update_before_restart", "explicit_private_stop",
    "explicit_private_newspawn", "actual_full_runtime_image",
    "real_registry_check", "baseline_install", "latest_update",
    "retained_operation", "same_key_identity", "installed_version",
    "legacy_final_integrity", "source_final_integrity",
)
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
SCOPE = re.compile(r"(?:OURO_(?:INSTALL|TASK|RUN)_SCOPE_[0-9a-fA-F]+|OURO_PROC_CONTAINER_[A-Za-z0-9_]+)\Z")
SEMVER = re.compile(r"v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.+-]+)?\Z")
PIN_VERSION = "4.4.0"
PIN_BUILD = "df0f5c03d9f9d5d18736662fd98e6a79368feecb"


class CheckFailure(RuntimeError):
    """Only fixed, non-secret diagnostic codes are placed in the public record."""


def require(condition, code):
    if not condition:
        raise CheckFailure(code)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def beneath(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def error_view(error):
    # Never serialize exception text, HTTP clients, handshake tokens or arbitrary
    # ControlProblem context. Unknown fields remain private on the runner.
    problem = getattr(error, "problem", None)
    context = problem.get("context", {}) if isinstance(problem, dict) else {}
    result = {"type": type(error).__name__, "code": getattr(error, "code", None),
              "status_code": getattr(error, "status_code", None)}
    if isinstance(error, CheckFailure):
        result["check"] = str(error)
    if isinstance(context, dict):
        result["acceptance"] = context.get("acceptance")
        result["scope"] = context.get("scope")
    return result


def inventory_row(body):
    rows = body.get("harnesses") if isinstance(body, dict) else None
    require(isinstance(rows, list), "inventory_not_list")
    selected = [r for r in rows if isinstance(r, dict) and r.get("harness") == "codex"]
    require(len(selected) == 1, "inventory_codex_not_unique")
    return selected[0]


def program_view(value):
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in ("version", "binary", "proved", "kind") if key in value}


def inventory_view(body):
    row = inventory_row(body)
    problem = row.get("availableProblem")
    operation = row.get("operation")
    return {"harness": row["harness"], "mechanism": row.get("mechanism"),
            "maintainable": row.get("maintainable"), "targets": row.get("targets"),
            "selection": program_view(row.get("selection")),
            "installed": program_view(row.get("installed")),
            "available": row.get("available"),
            "available_problem_code": problem.get("code") if isinstance(problem, dict) else None,
            "operation_id": operation.get("id") if isinstance(operation, dict) else None}


def operation_view(op):
    require(isinstance(op, dict), "operation_not_object")
    problem = op.get("problem")
    return {"id": op.get("id"), "harness": op.get("harness"), "state": op.get("state"),
            "phase": op.get("phase"), "mutation": op.get("mutation"),
            "termination": op.get("termination"), "target": op.get("target"),
            "before": program_view(op.get("before")), "after": program_view(op.get("after")),
            "problem_code": problem.get("code") if isinstance(problem, dict) else None}


def snapshot_files(root):
    root = Path(root)
    return {str(p.relative_to(root)).replace("\\", "/"): sha256(p)
            for p in sorted(root.rglob("*")) if p.is_file()}


def verify_source(source, lock_path, engine_version=PIN_VERSION, engine_build=PIN_BUILD, node_version="24.16.0"):
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    require(lock.get("schema_version") == 1 and lock.get("purpose") == "windows-1677-qualification", "source_lock_shape")
    observed = {}
    for name, expected in lock["source_files"].items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "source_lock_path")
        path = source / relative
        require(beneath(path, source), "source_link_outside")
        actual = sha256(path)
        require(actual == expected, "source_hash_mismatch:" + name)
        observed[name] = actual
    pin = json.loads((source / "ouroboros/claudexor_runtime_pin.json").read_text(encoding="utf-8"))["release"]
    require(pin["version"] == engine_version and pin["build_sha"] == engine_build, "wrong_engine_pin")
    require(pin["node_version"] == node_version, "wrong_node_pin")
    return {"lock_sha256": sha256(lock_path), "candidate_manifest_sha256": lock["candidate_manifest_sha256"],
            "candidate_base": lock["candidate_base"], "candidate_patch_sha256": lock["candidate_patch_sha256"],
            "candidate_paths": lock["candidate_paths"], "source_files": observed,
            "coverage": "candidate paths plus explicit consumed runtime/lifecycle/test-launcher files, not whole repository"}


def isolated_environment(root, source, inherited):
    # Called before importing any Ouroboros module. Windows homes for both Python
    # and every provider are explicit. No ProgramFiles, owner PATH, proxy, token,
    # NODE_OPTIONS, engine attachment, account pin or auth environment is inherited.
    require(sys.platform == "win32", "requires_native_windows")
    win = Path(inherited.get("SystemRoot", inherited.get("SYSTEMROOT", "C:/Windows"))).resolve()
    require(win.is_absolute() and (win / "System32/kernel32.dll").is_file(), "invalid_windows_root")
    env = {k: v for k, v in inherited.items() if SCOPE.fullmatch(k) and v == "1"}
    env.update({"SystemRoot": str(win), "WINDIR": str(win), "ComSpec": str(win / "System32/cmd.exe"),
                "PATH": str(win / "System32"), "PATHEXT": ".COM;.EXE;.BAT;.CMD",
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "OUROBOROS_PYTEST_ACTIVE": "1", "OUROBOROS_TEST_TEMP_ROOT": str(root),
                "OUROBOROS_REPO_DIR": str(source), "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": str(root / "no-gitconfig"), "GIT_OPTIONAL_LOCKS": "0",
                "GIT_CEILING_DIRECTORIES": str(root), "npm_config_registry": "https://registry.npmjs.org/",
                "npm_config_update_notifier": "false", "npm_config_audit": "false", "npm_config_fund": "false"})
    paths = {"HOME": "home", "USERPROFILE": "home", "APPDATA": "home/appdata",
             "LOCALAPPDATA": "home/localappdata", "XDG_CONFIG_HOME": "home/config",
             "XDG_CACHE_HOME": "home/cache", "XDG_DATA_HOME": "home/data", "XDG_STATE_HOME": "home/state",
             "TMP": "tmp", "TEMP": "tmp", "TMPDIR": "tmp", "PYTHONUSERBASE": "userbase",
             "OUROBOROS_APP_ROOT": "app", "OUROBOROS_DATA_DIR": "data",
             "OUROBOROS_SUBAGENT_PROJECTS_ROOT": "projects", "OUROBOROS_SUBAGENT_WORKTREE_ROOT": "worktrees",
             "OUROBOROS_DELIVERABLES_ROOT": "Deliverables", "CLAUDEXOR_CONFIG_DIR": "data/claudexor",
             "CLAUDE_CONFIG_DIR": "home/.claude", "CODEX_HOME": "home/.codex", "COPILOT_HOME": "home/.copilot",
             "npm_config_prefix": "home/npm", "npm_config_cache": "home/npm-cache"}
    for key, relative in paths.items():
        target = root / relative
        target.mkdir(parents=True, exist_ok=True)
        env[key] = str(target)
    env["OUROBOROS_SETTINGS_PATH"] = str(root / "data/settings.json")
    env["OUROBOROS_BUNDLE_DIR"] = str(root / "bundle")
    for name in ("node", "npm", "npx", "codex", "claude", "claudexor", "claudexord"):
        require(shutil.which(name, path=env["PATH"]) is None, "ambient_program:" + name)
    return env


class NativeProcess:
    """Hold an OS handle across the observation/stop, so PID reuse proves nothing."""
    def __init__(self, proc):
        from ctypes import wintypes as w
        self.pid = proc.pid
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.api.OpenProcess.restype = w.HANDLE
        self.api.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        self.api.QueryFullProcessImageNameW.restype = w.BOOL
        self.api.GetProcessTimes.argtypes = [w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)]
        self.api.GetProcessTimes.restype = w.BOOL
        self.api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        self.api.WaitForSingleObject.restype = w.DWORD
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.handle = self.api.OpenProcess(0x1000 | 0x00100000, False, proc.pid)
        require(bool(self.handle), "OpenProcess_failed")
        try:
            size = w.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            require(self.api.QueryFullProcessImageNameW(self.handle, 0, buf, ctypes.byref(size)), "QueryFullProcessImageName_failed")
            self.image = str(Path(buf.value).resolve())
            times = [w.FILETIME() for _ in range(4)]
            require(self.api.GetProcessTimes(self.handle, *[ctypes.byref(v) for v in times]), "GetProcessTimes_failed")
            self.created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        except BaseException:
            self.close()
            raise

    def alive(self):
        result = self.api.WaitForSingleObject(self.handle, 0)
        require(result in (0, 258), "WaitForSingleObject_failed")
        return result == 258

    def view(self):
        return {"pid": self.pid, "creation_filetime": self.created, "executable_image": self.image,
                "alive": self.alive(), "observation": "Win32 held HANDLE / QueryFullProcessImageNameW / GetProcessTimes"}

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class Probe:
    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        source = args.source_root.resolve()
        require(not beneath(self.output, source) and not beneath(source, self.output), "output_overlaps_source")
        require(not any((p / ".git").exists() for p in (self.output, *self.output.parents)), "output_has_git_ancestor")
        self.output.mkdir(parents=True, exist_ok=False)
        self.started = time.monotonic()
        self.deadline = self.started + args.work_seconds
        self.record = {"schema_version": 1, "native_execution": "attempted", "outcome": "running",
                       "gaps": ["Packaged-style Node-only fixture, not a built Windows application or GUI test.",
                                "Environment isolation is not an OS security sandbox.",
                                "No login, account, model-generation, real Agent-session PATH, Linux or macOS qualification."],
                       "phases": [{"name": name, "status": "NOT_RUN"} for name in PHASES],
                       "cleanup": {"status": "not_started"}, "requests": []}
        self.daemon = self.heartbeat = self.active_operation = None
        self.sink = None
        self.handles = []
        self.service = None
        self.create_calls = 0
        self.inventory_calls = 0
        self.profile_file = None
        self.profile_active = False
        self.save()

    def verify_source(self):
        return verify_source(self.args.source_root.resolve(), self.args.source_lock,
                             self.args.engine_version, self.args.engine_build, self.args.node_version)

    def observe_control_call(self, frame, event, _arg):
        # Observe the real synchronous gateway function; no transport, response,
        # body or header is replaced. Counter only: never retain frame locals.
        if (event == "call" and frame.f_code.co_name == "_request"
                and Path(frame.f_code.co_filename).resolve() == self.profile_file):
            method, path = frame.f_locals.get("method"), frame.f_locals.get("path")
            if method == "POST" and path == "/v2/maintenance/operations":
                self.create_calls += 1
            if method == "GET" and isinstance(path, str) and path.startswith("/v2/maintenance/harnesses?"):
                self.inventory_calls += 1

    def save(self):
        self.record["control_observation"] = {"maintenance_create_calls": self.create_calls,
            "maintenance_inventory_calls": self.inventory_calls,
            "coverage": "actual synchronous host gateway _request calls, not a packet capture or other threads"}
        self.record["elapsed_seconds"] = round(time.monotonic() - self.started, 3)
        write_json(self.output / "receipt.json", self.record)

    def check_time(self, reserve=90):
        require(time.monotonic() + reserve < self.deadline, "work_deadline_reached")

    @contextlib.contextmanager
    def phase(self, name):
        self.check_time()
        row = next(row for row in self.record["phases"] if row["name"] == name)
        row.update(status="RUNNING", started_seconds=round(time.monotonic() - self.started, 3))
        self.save()
        try:
            yield row
        except BaseException as exc:
            row.update(status="FAIL", error=error_view(exc))
            raise
        else:
            row["status"] = "PASS"
        finally:
            self.save()
            print(json.dumps({"phase": name, "status": row["status"]}), flush=True)

    def command(self, argv, timeout=30):
        # Output is only parsed for an exact version, never copied into uploads.
        require(Path(argv[0]).is_absolute(), "command_not_absolute")
        commands = self.record.setdefault("commands", [])
        row = {"argv": [str(a) for a in argv], "state": "running"}
        commands.append(row)
        self.save()
        try:
            result = subprocess.run([str(a) for a in argv], cwd=self.root, env=dict(os.environ),
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            stdout, stderr = result.stdout, result.stderr
            row.update(state="returned", exit_code=result.returncode)
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = exc.stdout or b"", exc.stderr or b""
            row.update(state="timeout", exit_code=None)
        private = self.root / ("version-command-" + str(len(commands)))
        private.with_suffix(".stdout").write_bytes(stdout)
        private.with_suffix(".stderr").write_bytes(stderr)
        row.update(stdout_sha256=hashlib.sha256(stdout).hexdigest(), stdout_bytes=len(stdout), stderr_bytes=len(stderr),
                   private_output_prefix=str(private), raw_output_exported=False)
        self.save()
        require(row["state"] == "returned", "version_command_timed_out")
        require(row["exit_code"] == 0, "version_command_failed")
        text = stdout.decode("utf-8", errors="replace").strip()
        require(SEMVER.fullmatch(text) is not None, "unexpected_version_output")
        row["version"] = text
        self.save()
        return {"exit_code": row["exit_code"], "version": text, "stdout_sha256": row["stdout_sha256"], "stderr_bytes": len(stderr)}

    def serving(self):
        from ouroboros.claudexor_daemon import read_owned_gateway
        proc = self.daemon._proc
        require(proc is not None and proc.poll() is None, "owned_process_not_live")
        native = NativeProcess(proc)
        self.handles.append(native)
        with read_owned_gateway() as gateway:
            handshake = gateway.handshake()
            version, build = gateway.engine_version, gateway.engine_build_sha
        require(version == self.args.engine_version and build == self.args.engine_build, "serving_engine_mismatch")
        engine = handshake.get("engine", {})
        entry = engine.get("entry") if isinstance(engine, dict) else None
        require(isinstance(entry, str) and beneath(entry, self.root), "engine_entry_outside_private_root")
        return native, {**native.view(), "engine_version": version, "engine_build_sha": build,
                        "engine_entry": entry, "protocol_major": handshake.get("protocolMajor")}

    def legacy_ok(self):
        require(self.heartbeat is not None and self.heartbeat.poll() is None, "legacy_reader_exited")
        require(snapshot_files(self.legacy) == self.legacy_before, "legacy_tree_changed")
        # Verify continued reads AFTER a preparation/stop boundary, not only that
        # the process once printed a line and remained alive.
        previous = self.heartbeat_log.stat().st_size
        until = time.monotonic() + 5
        while self.heartbeat_log.stat().st_size <= previous and time.monotonic() < until:
            time.sleep(0.1)
        require(self.heartbeat.poll() is None and self.heartbeat_log.stat().st_size > previous, "legacy_reader_not_advancing")
        return {"legacy_files_sha256": self.legacy_before, "reader_pid": self.heartbeat.pid,
                "reader_output_bytes": self.heartbeat_log.stat().st_size, "reader_advances": True}

    def prepared_only(self, key):
        request = {"harness": "codex", "target": {"kind": "latest"}}
        self.record["requests"].append({"key": key, "body": request, "expected": "preparation_only"})
        self.save()  # Write intent before the actual service call.
        try:
            answer = self.service.start_maintenance(request, key)
        except self.unavailable as exc:
            problem = getattr(exc, "problem", None)
            require(exc.code == "maintenance_restart_required" and exc.status_code == 409, "not_preparation_ready")
            context = problem.get("context", {}) if isinstance(problem, dict) else {}
            require(context.get("acceptance") == "not_submitted" and context.get("scope") == "this_attempt"
                    and context.get("requestId") == key and context.get("preparation") == "ready"
                    and context.get("restartRequired") is True, "invalid_preparation_scope")
            node = Path(context.get("node") or "")
            require(node.is_absolute() and beneath(node, self.root) and node.is_file(), "prepared_node_outside")
            require(self.manager._managed_npm_cli(node).is_file(), "prepared_npm_missing")
            return node, {"code": exc.code, "status_code": exc.status_code,
                          "acceptance": "not_submitted", "scope": "this_attempt", "preparation": "ready", "node": str(node)}
        self.record["unexpected_operation"] = operation_view(answer)
        if isinstance(answer.get("id"), str):
            self.active_operation = answer
        raise CheckFailure("update_unexpectedly_submitted")

    def maintain(self, kind, key):
        self.check_time(180)
        request = {"harness": "codex", "target": {"kind": kind}}
        intent = {"key": key, "body": request, "acceptance": "unknown", "operation": None}
        self.record["requests"].append(intent)
        self.save()
        # Exactly one POST. A lost reply terminates this experiment with its key
        # retained; do not manufacture a second invocation or automatic retry.
        before_creates = self.create_calls
        op = self.service.start_maintenance(request, key)
        self.active_operation = op
        require(self.create_calls == before_creates + 1, "real_create_observer_not_calibrated_or_retried")
        intent.update(acceptance="received_operation", operation=operation_view(op))
        self.save()
        until = min(self.deadline, time.monotonic() + self.args.operation_seconds)
        while op.get("state") not in TERMINAL:
            require(time.monotonic() + 65 < until, "operation_poll_deadline")
            time.sleep(1)
            op = self.service.inspect_operation(op["id"])
            self.active_operation = op
            intent["operation"] = operation_view(op)
            self.save()
        require(op["state"] == "succeeded" and op.get("mutation") == "applied", "real_vendor_operation_failed")
        require(op.get("harness") == "codex", "wrong_vendor_operation")
        after = op.get("after")
        require(isinstance(after, dict) and isinstance(after.get("version"), str), "operation_no_after_version")
        self.active_operation = None
        return op

    def run(self):
        with self.phase("boundary_and_source") as phase:
            require(sys.platform == "win32", "requires_native_windows")
            source = self.args.source_root.resolve()
            parent_root = os.environ.get("OUROBOROS_TEST_TEMP_ROOT")
            require(parent_root is not None, "safe_test_required")
            self.root = Path(parent_root).resolve()
            require(self.root.name.startswith("ob-") and not beneath(self.root, source), "unsafe_test_root")
            for parent in (self.root, *self.root.parents):
                require(not (parent / ".git").exists(), "scratch_has_git_ancestor")
            for key in ("HOME", "OUROBOROS_DATA_DIR", "OUROBOROS_SETTINGS_PATH"):
                require(key in os.environ and beneath(os.environ[key], self.root), "safe_test_boundary_missing:" + key)
            require(not (self.root / "data/claudexor").exists(), "private_engine_home_not_fresh")
            env = isolated_environment(self.root, source, dict(os.environ))
            os.environ.clear()
            os.environ.update(env)
            os.chdir(self.root)
            self.record["source"] = self.verify_source()
            self.record["environment"] = {k: env[k] for k in ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "CLAUDEXOR_CONFIG_DIR", "CODEX_HOME")}
            self.record["custody_markers"] = sorted(k for k in env if SCOPE.fullmatch(k))
            self.record["platform"] = {"sys_platform": sys.platform, "windows_version": list(sys.getwindowsversion()[:3])}
            sys.path.insert(0, str(source))
            from ouroboros import claudexor_runtime as runtime, harness_maintenance as service
            from ouroboros.claudexor_daemon import get_owned_daemon
            from ouroboros.gateways.claudexor import ClaudexorUnavailable
            from ouroboros.platform_layer import node_distribution_platform
            self.service, self.unavailable = service, ClaudexorUnavailable
            self.manager, self.daemon = runtime.get_runtime_manager(), get_owned_daemon()
            require(os.environ.get("PATH") == env["PATH"], "product_import_changed_path")
            require(node_distribution_platform() == "win32-x64", "requires_windows_x64")
            pin = self.manager.pin
            require(pin is not None and pin.version == self.args.engine_version and pin.build_sha == self.args.engine_build, "manager_pin_mismatch")
            require(sys.getprofile() is None, "unexpected_existing_profiler")
            self.profile_file = (source / "ouroboros/gateways/claudexor.py").resolve()
            sys.setprofile(self.observe_control_call)
            self.profile_active = True
            phase["detail"] = {"platform": "win32-x64", "source_verified": True}

        with self.phase("packaged_node_fixture") as phase:
            artifact = pin.node_artifacts["win32-x64"]
            archive = self.root / "input-node.zip"
            runtime.fetch_node_archive(artifact, archive)
            runtime.verify_node_archive(archive, artifact)
            self.bundle_node = self.root / "bundle/node-standalone/node.exe"
            self.bundle_node.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive) as opened:
                entry = opened.getinfo(artifact.executable)
                require(entry.file_size > 0 and not entry.is_dir(), "node_archive_entry_invalid")
                with opened.open(entry) as src, self.bundle_node.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
            require(not self.manager._managed_npm_cli(self.bundle_node).exists(), "fixture_has_npm")
            phase["detail"] = {"archive_sha256": sha256(archive), "archive_bytes": archive.stat().st_size,
                               "node_sha256": sha256(self.bundle_node), "node": self.command([self.bundle_node, "--version"]),
                               "fixture": "exact Node extracted alone from pinned full ZIP; no npm copied"}

        with self.phase("legacy_live_reader") as phase:
            self.legacy = runtime.managed_node_dir(pin, "win32-x64")
            legacy_node = self.legacy / "node-standalone/node.exe"
            legacy_node.parent.mkdir(parents=True)
            shutil.copy2(self.bundle_node, legacy_node)
            metadata = {"schema_version": 1, "version": pin.node_version, "platform": "win32-x64",
                        "archive_url": artifact.archive_url, "archive_sha256": artifact.sha256,
                        "archive_size": artifact.size_bytes, "archive_executable": artifact.executable}
            write_json(self.legacy / "managed-node.json", metadata)
            module = self.legacy / "heartbeat.cjs"
            module.write_text("module.exports = 1677;\n", encoding="utf-8")
            self.legacy_before = snapshot_files(self.legacy)
            self.heartbeat_log = self.root / "heartbeat.log"
            self.sink = self.heartbeat_log.open("wb")
            code = "setInterval(()=>{delete require.cache[require.resolve(process.argv[1])];console.log(require(process.argv[1]));},100)"
            self.heartbeat = subprocess.Popen([str(legacy_node), "-e", code, str(module)], cwd=self.root,
                                             env=dict(os.environ), stdin=subprocess.DEVNULL, stdout=self.sink,
                                             stderr=self.sink, creationflags=subprocess.CREATE_NO_WINDOW)
            heartbeat_handle = NativeProcess(self.heartbeat)
            self.handles.append(heartbeat_handle)
            phase["detail"] = heartbeat_handle.view()
            time.sleep(0.5)
            self.legacy_ok()

        with self.phase("initial_private_start") as phase:
            from ouroboros.claudexor_daemon import ensure_owned_gateway
            with ensure_owned_gateway() as gateway:
                require(gateway.engine_version == self.args.engine_version and gateway.engine_build_sha == self.args.engine_build, "initial_engine_mismatch")
            first, phase["detail"] = self.serving()
            require(Path(first.image) == self.bundle_node.resolve(), "not_packaged_node_image")

        with self.phase("check_latest_installs_nothing") as phase:
            before_creates, before_reads = self.create_calls, self.inventory_calls
            before_node = snapshot_files(self.legacy.parent)
            before = self.service.inspect_harnesses(["codex"], fresh=True)
            checked = self.service.inspect_harnesses(["codex"], fresh=True, check_latest=True)
            row = inventory_row(checked)
            require((row.get("availableProblem") or {}).get("code") == "embedded_npm_missing", "missing_npm_not_observed")
            require((row.get("installed") or {}).get("binary") is None and row.get("operation") is None, "check_latest_installed_cli")
            require((inventory_row(before).get("installed") or {}).get("version") is None, "initial_cli_not_empty")
            require(snapshot_files(self.legacy.parent) == before_node, "check_latest_changed_node_files")
            require(self.create_calls == before_creates, "check_latest_submitted_maintenance")
            require(self.inventory_calls >= before_reads + 2, "real_read_observer_not_calibrated")
            phase["detail"] = inventory_view(checked)

        key = "ob1677-" + uuid.uuid4().hex
        self.record["update_key"] = key
        with self.phase("update_prepares_only") as phase:
            before_creates = self.create_calls
            ready, phase["detail"] = self.prepared_only(key)
            require(self.create_calls == before_creates, "preparation_submitted_maintenance")
            require(ready.resolve() != self.bundle_node.resolve() and not beneath(ready, self.legacy), "prepared_in_old_root")
            require(sha256(ready) == sha256(self.bundle_node), "prepared_node_not_same_pinned_image")
            phase["detail"]["npm_version"] = self.command([ready, self.manager._managed_npm_cli(ready), "--version"])
            require(inventory_row(self.service.inspect_harnesses(["codex"], fresh=True)).get("operation") is None, "preparation_created_operation")
            generation_before_repeat = snapshot_files(ready.parent.parent)

        with self.phase("preparation_preserves_live_process") as phase:
            require(first.alive() and self.daemon._proc.pid == first.pid, "preparation_displaced_process")
            current, current_view = self.serving()
            require(current.pid == first.pid and current.created == first.created and current.image == first.image, "original_process_identity_changed")
            phase["detail"] = {"serving": current_view, "legacy": self.legacy_ok()}

        with self.phase("repeat_update_before_restart") as phase:
            before_creates = self.create_calls
            repeated, phase["detail"] = self.prepared_only(key)
            require(self.create_calls == before_creates, "repeat_preparation_submitted_maintenance")
            require(repeated.resolve() == ready.resolve(), "repeat_preparation_selected_another_generation")
            require(snapshot_files(ready.parent.parent) == generation_before_repeat, "repeat_preparation_changed_generation")
            require(first.alive() and self.daemon._proc.pid == first.pid, "repeat_displaced_process")
            require(inventory_row(self.service.inspect_harnesses(["codex"], fresh=True)).get("operation") is None, "repeat_preparation_created_operation")

        with self.phase("explicit_private_stop") as phase:
            outcome = self.daemon.stop_outcome()
            require(outcome == "stopped" and not first.alive(), "private_stop_unconfirmed")
            phase["detail"] = {"outcome": outcome, "old_process": first.view()}
        with self.phase("explicit_private_newspawn") as phase:
            with ensure_owned_gateway() as gateway:
                require(gateway.engine_version == self.args.engine_version and gateway.engine_build_sha == self.args.engine_build, "new_engine_mismatch")
            second, phase["detail"] = self.serving()
        with self.phase("actual_full_runtime_image") as phase:
            require(second.alive() and second.created != first.created and not first.alive(), "not_new_process_identity")
            require(Path(second.image) == ready.resolve(), "new_process_did_not_select_full_runtime")
            phase["detail"] = {"actual": second.view(), "expected_node": str(ready), "same_pid_reused": second.pid == first.pid}
        with self.phase("real_registry_check") as phase:
            checked = self.service.inspect_harnesses(["codex"], fresh=True, check_latest=True)
            row = inventory_row(checked)
            require(row.get("available") is not None and not row.get("availableProblem"), "registry_check_not_successful")
            require(row.get("mechanism") == "managed_npm" and {"baseline", "latest"}.issubset(row.get("targets", [])), "codex_not_managed_by_engine")
            phase["detail"] = inventory_view(checked)
        with self.phase("baseline_install") as phase:
            baseline = self.maintain("baseline", key + "-baseline")
            phase["detail"] = operation_view(baseline)
        with self.phase("latest_update") as phase:
            updated = self.maintain("latest", key)
            require(baseline["after"]["version"] != updated["after"]["version"], "baseline_equals_latest_no_update_proven")
            phase["detail"] = operation_view(updated)
        with self.phase("retained_operation") as phase:
            retained = self.service.inspect_operation(updated["id"])
            require(retained["id"] == updated["id"] and retained["state"] == "succeeded", "retained_operation_mismatch")
            phase["detail"] = operation_view(retained)
        with self.phase("same_key_identity") as phase:
            before_creates = self.create_calls
            replay = self.service.start_maintenance({"harness": "codex", "target": {"kind": "latest"}}, key)
            require(self.create_calls == before_creates + 1, "replay_create_count_mismatch")
            self.active_operation = replay if replay.get("state") not in TERMINAL else None
            require(replay["id"] == updated["id"] and replay["state"] == "succeeded", "same_key_created_other_operation")
            phase["detail"] = operation_view(replay)
        with self.phase("installed_version") as phase:
            checked = self.service.inspect_harnesses(["codex"], fresh=True)
            installed = inventory_row(checked).get("installed") or {}
            require(installed.get("proved") is True and installed.get("version") == updated["after"]["version"], "installed_version_not_proved")
            require(isinstance(installed.get("binary"), str) and beneath(installed["binary"], self.root), "installed_binary_not_private")
            phase["detail"] = inventory_view(checked)
        with self.phase("legacy_final_integrity") as phase:
            phase["detail"] = self.legacy_ok()
        with self.phase("source_final_integrity") as phase:
            require(self.verify_source() == self.record["source"], "source_changed_during_run")
            phase["detail"] = {"source_unchanged": True}

    def cleanup(self):
        cleanup = self.record["cleanup"]
        cleanup.update(status="running", daemon="not_started", heartbeat="not_started")
        self.save()
        if self.service is not None and self.active_operation is not None:
            try:
                op = self.active_operation
                if op.get("state") not in TERMINAL:
                    op = self.service.cancel_maintenance(op["id"])
                    cleanup["cancel"] = operation_view(op)
                    op = self.service.inspect_operation(op["id"])
                    cleanup["cancel_readback"] = operation_view(op)
                    cleanup["operation_settled"] = op.get("state") in TERMINAL and op.get("termination") != "unconfirmed"
                else:
                    cleanup["operation_settled"] = op.get("termination") != "unconfirmed"
            except BaseException as exc:
                cleanup["operation_error"] = error_view(exc)
                cleanup["operation_settled"] = False
        if self.daemon is not None:
            try:
                cleanup["daemon"] = self.daemon.stop_outcome()
                cleanup["daemon_handle_reaped"] = self.daemon._proc is None or self.daemon._proc.poll() is not None
            except BaseException as exc:
                cleanup["daemon_error"] = error_view(exc)
        if self.heartbeat is not None:
            try:
                if self.heartbeat.poll() is None:
                    self.heartbeat.terminate()  # This exact owned Popen, never an image-name/process scan.
                self.heartbeat.wait(timeout=10)
                cleanup["heartbeat"] = "exited"
                cleanup["heartbeat_returncode"] = self.heartbeat.returncode
            except BaseException as exc:
                cleanup["heartbeat"] = "unconfirmed"
                cleanup["heartbeat_error"] = error_view(exc)
        if self.sink is not None:
            try:
                self.sink.close()
            except OSError as exc:
                cleanup["heartbeat_log_close_error"] = error_view(exc)
        cleanup["native_handles"] = []
        for handle in self.handles:
            try:
                cleanup["native_handles"].append(handle.view())
            except BaseException as exc:
                cleanup["native_handles"].append({"error": error_view(exc)})
            finally:
                handle.close()
        settled = (cleanup["daemon"] in {"not_started", "stopped", "nothing_to_stop"}
                   and cleanup["heartbeat"] in {"not_started", "exited"}
                   and cleanup.get("operation_settled", True)
                   and all(row.get("alive") is False for row in cleanup["native_handles"]))
        cleanup["status"] = "confirmed" if settled else "unconfirmed"
        # Keep the fresh prefix for safe_test's measured cleanup classification;
        # never delete a tree merely because the top-level command has returned.
        if self.profile_active:
            sys.setprofile(None)
            self.profile_active = False
        self.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, default=Path(__file__).with_name("source-lock.json"))
    parser.add_argument("--output", type=Path, required=True, help="new allowlisted upload directory; must not exist")
    parser.add_argument("--engine-version", default=PIN_VERSION)
    parser.add_argument("--engine-build", default=PIN_BUILD)
    parser.add_argument("--node-version", default="24.16.0")
    parser.add_argument("--work-seconds", type=int, default=900)
    parser.add_argument("--operation-seconds", type=int, default=240)
    args = parser.parse_args(argv)
    require(300 <= args.work_seconds <= 1200 and 90 <= args.operation_seconds <= 300, "invalid_deadline_bounds")
    probe = Probe(args)
    passed = False
    try:
        probe.run()
        passed = True
    except BaseException as exc:
        probe.record["error"] = error_view(exc)
    finally:
        probe.cleanup()
        probe.record["outcome"] = "PASS" if passed and probe.record["cleanup"]["status"] == "confirmed" else "PARTIAL_FAIL"
        probe.record["native_execution"] = "executed" if sys.platform == "win32" else "NOT_RUN"
        probe.save()
    return 0 if probe.record["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
